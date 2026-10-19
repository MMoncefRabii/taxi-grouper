"""
Training data capture and management for auto-learning from user corrections.

When a user corrects the automated grouping, this module extracts the corrections
as training examples to improve future grouping decisions.
"""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import tempfile
import threading
import unicodedata
import logging
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from typing import Any

import pandas as pd
from sklearn.metrics import accuracy_score

from src.config import DEFAULT_CANDIDATE_MODEL_PATH, DEFAULT_MODEL_PATH
from src.core.ml_model import (
    HISTORIQUE_COLUMNS,
    load_model,
    train_model_from_historique_excel,
    prepare_historique_pairwise_examples,
)
from src.core.model_storage import ensure_model_write_allowed

logger = logging.getLogger(__name__)

AUTO_TRAINING_JSONL_PATH = Path("data/auto_training_corrections.jsonl")
AUTO_TRAINING_DEBUG_JSONL_PATH = Path("data/auto_training_corrections.debug.jsonl")
RETRAIN_STATE_PATH = Path("data/retrain_state.json")
CANDIDATE_MODEL_DIR = DEFAULT_CANDIDATE_MODEL_PATH.parent
CANDIDATE_MODEL_PATH = DEFAULT_CANDIDATE_MODEL_PATH
EVALUATION_REPORT_PATH = DEFAULT_MODEL_PATH.parent / "evaluation_report.json"
PRE_CORRECTION_CACHE_DIR = Path("data/pre_correction_cache")

_PRE_CORRECTION_CACHE_LOCK = threading.Lock()
_AUTO_TRAINING_JSONL_LOCK = threading.Lock()
_RETRAIN_STATE_LOCK = threading.Lock()
_MODEL_PROMOTION_LOCK = threading.Lock()


def _get_training_corrections_path() -> Path:
    """Get the appropriate training corrections file based on DEBUG environment.
    
    When DEBUG=1, uses a separate debug file so test data never contaminates production.
    When DEBUG is absent/unset, uses the production file.
    """
    if os.getenv("DEBUG") == "1":
        return AUTO_TRAINING_DEBUG_JSONL_PATH
    return AUTO_TRAINING_JSONL_PATH


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, dir=str(path.parent), suffix=".tmp", mode="w", encoding="utf-8") as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


def _pre_correction_state_path(sheet_id: str) -> Path:
    safe_id = urllib.parse.quote_plus(sheet_id)
    return PRE_CORRECTION_CACHE_DIR / f"{safe_id}.json"


def _ensure_pre_correction_dir() -> None:
    PRE_CORRECTION_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _save_pre_correction_state(sheet_id: str, grouped_df: pd.DataFrame) -> None:
    _ensure_pre_correction_dir()
    path = _pre_correction_state_path(sheet_id)
    with _PRE_CORRECTION_CACHE_LOCK:
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, dir=str(path.parent), suffix=".tmp") as tmp:
                tmp_path = Path(tmp.name)
            grouped_df.to_json(tmp_path, orient="split", force_ascii=False)
            os.replace(tmp_path, path)
        finally:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass


def _load_pre_correction_state(sheet_id: str) -> pd.DataFrame | None:
    path = _pre_correction_state_path(sheet_id)
    if not path.exists():
        return None
    try:
        return pd.read_json(path, orient="split")
    except Exception:
        return None


def _delete_pre_correction_state(sheet_id: str) -> None:
    path = _pre_correction_state_path(sheet_id)
    with _PRE_CORRECTION_CACHE_LOCK:
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass


def store_pre_correction_state(sheet_id: str, grouped_df: pd.DataFrame) -> None:
    """Store the grouped state before user corrections.
    
    This is called after grouping but before the user edits the sheet.
    Allows us to compare before/after to extract training examples.
    
    Args:
        sheet_id: Google Sheet ID
        grouped_df: The grouped DataFrame that was written to the sheet
    """
    _save_pre_correction_state(sheet_id, grouped_df)
    logger.debug(f"Persisted pre-correction state for sheet {sheet_id}: {len(grouped_df)} rows")


def clear_pre_correction_state(sheet_id: str) -> None:
    """Clear the cached pre-correction state for a sheet."""
    _delete_pre_correction_state(sheet_id)


def get_pre_correction_cache_size() -> int:
    """Return the number of sheets currently stored in pre-correction state."""
    _ensure_pre_correction_dir()
    return len(list(PRE_CORRECTION_CACHE_DIR.glob("*.json")))


def extract_training_examples_from_corrections(
    sheet_id: str,
    post_correction_df: pd.DataFrame,
    taxi_column: str = "Groupe Taxi"
) -> dict[str, Any]:
    """
    Compare pre-correction and post-correction states to extract training examples.
    
    Returns a dict with:
    - corrections: list of changed assignments
    - stats: summary of changes
    - success: whether extraction succeeded
    
    A "correction" is a row where the taxi assignment changed.
    Each correction becomes a training example showing:
    - The agent/address features
    - The original (incorrect) taxi assignment
    - The corrected (correct) taxi assignment
    
    Args:
        sheet_id: Google Sheet ID
        post_correction_df: The corrected DataFrame read back from the sheet
        taxi_column: Name of the taxi grouping column
        
    Returns:
        Dict with corrections and statistics
    """
    logger.debug(f"Extracting corrections for sheet {sheet_id}")
    logger.debug(f"Looking for sheet_id: {sheet_id}")

    if post_correction_df.attrs.get("merge_info_available") is False:
        return {
            "success": False,
            "error": "Merge information unavailable; correction capture skipped",
            "corrections": [],
            "stats": {
                "status": "merge_info_unavailable",
                "total_rows": len(post_correction_df),
                "rows_changed": 0,
            },
        }

    pre_df = _load_pre_correction_state(sheet_id)
    if pre_df is None:
        logger.warning(f"No pre-correction state cached for sheet {sheet_id}")
        available = [p.stem for p in PRE_CORRECTION_CACHE_DIR.glob("*.json")] if PRE_CORRECTION_CACHE_DIR.exists() else []
        logger.warning(f"Available sheets in cache: {available}")
        return {
            "success": False,
            "error": "No pre-correction state available",
            "corrections": [],
            "stats": {}
        }
    
    logger.debug(f"Found pre-correction state: {len(pre_df)} rows")
    
    # Verify both DataFrames have the same structure
    if len(pre_df) != len(post_correction_df):
        logger.warning(f"Row count mismatch: pre={len(pre_df)}, post={len(post_correction_df)}")
        return {
            "success": False,
            "error": f"Row count changed during correction ({len(pre_df)} -> {len(post_correction_df)})",
            "corrections": [],
            "stats": {}
        }
    
    if taxi_column not in pre_df.columns or taxi_column not in post_correction_df.columns:
        logger.error(f"Taxi column '{taxi_column}' not found in correction data")
        logger.error(f"Pre-correction columns: {list(pre_df.columns)}")
        logger.error(f"Post-correction columns: {list(post_correction_df.columns)}")
        return {
            "success": False,
            "error": f"Taxi column '{taxi_column}' not found",
            "corrections": [],
            "stats": {}
        }
    
    # Find rows where the taxi assignment changed
    corrections = []
    changed_indices = []

    def _normalize_taxi_assignment(value: Any) -> str:
        if value is None or pd.isna(value):
            return ""
        normalized = str(value).strip()
        return "" if normalized.lower() in {"", "nan"} else normalized

    # Fields we consider volatile/noisy and should be ignored for fingerprinting
    VOLATILE_FIELDS = {"heure d'arrivée", 'prix', 'timestamp', 'score', 'internal_score', 'last_updated', 'updated_at'}

    # Helper: fingerprint a row excluding the taxi column so we can compare membership
    def _json_default(o):
        try:
            return o.item()
        except Exception:
            return str(o)

    def _row_fingerprint(series: pd.Series) -> str:
        # Exclude taxi column and volatile fields (case-insensitive)
        row_dict = {}
        for k, v in series.to_dict().items():
            if k == taxi_column:
                continue
            if isinstance(k, str) and k.strip().lower() in VOLATILE_FIELDS:
                continue
            row_dict[k] = v
        try:
            # Normalize unicode in keys and string values to prevent encoding corruption
            def _norm_obj(o):
                if isinstance(o, str):
                    return unicodedata.normalize('NFC', o)
                if isinstance(o, dict):
                    return {unicodedata.normalize('NFC', str(kk)): _norm_obj(vv) for kk, vv in o.items()}
                if isinstance(o, list):
                    return [_norm_obj(x) for x in o]
                return o

            norm = _norm_obj(row_dict)
            return json.dumps(norm, sort_keys=True, ensure_ascii=False, default=_json_default)
        except Exception:
            return str(row_dict)

    # Precompute fingerprints per index for membership comparisons
    pre_fps = {idx: _row_fingerprint(pre_df.loc[idx]) for idx in pre_df.index}
    post_fps = {idx: _row_fingerprint(post_correction_df.iloc[idx]) for idx in post_correction_df.index}

    # Build group -> set(fingerprints) maps
    pre_groups: dict[str, set] = {}
    post_groups: dict[str, set] = {}
    for idx in pre_df.index:
        key = _normalize_taxi_assignment(pre_df.loc[idx, taxi_column])
        pre_groups.setdefault(key, set()).add(pre_fps[idx])
    for idx in post_correction_df.index:
        key = _normalize_taxi_assignment(post_correction_df.iloc[idx][taxi_column])
        post_groups.setdefault(key, set()).add(post_fps[idx])

    # Matching remains positional; row insertion, deletion, or reordering can misattribute changes.
    for idx in pre_df.index:
        pre_taxi = _normalize_taxi_assignment(pre_df.loc[idx, taxi_column])
        post_taxi = _normalize_taxi_assignment(post_correction_df.iloc[idx][taxi_column])

        if pre_taxi != post_taxi and pre_taxi and post_taxi:
            # Semantic check: if the full membership of the source group equals the target group's membership,
            # then this is likely a pure relabeling (cosmetic renumbering) and should be skipped.
            pre_members = pre_groups.get(pre_taxi, set())
            post_members = post_groups.get(post_taxi, set())
            if pre_members == post_members:
                logger.info(f"Skipping cosmetic renumbering for row {idx}: group '{pre_taxi}' -> '{post_taxi}'")
                continue

            changed_indices.append(idx)
            correction = {
                "row_index": int(idx) if isinstance(idx, int) else idx,
                "before": pre_taxi,
                "after": post_taxi,
                "row_data": post_correction_df.iloc[idx].to_dict()  # Store corrected data
            }
            corrections.append(correction)

    detected_count = len(corrections)
    if len(pre_df) > 0 and detected_count > len(pre_df) * 0.5:
        logger.warning(
            "Correction capture rejected by sanity limit: corrections=%d rows=%d",
            detected_count,
            len(pre_df),
        )
        clear_pre_correction_state(sheet_id)
        return {
            "success": True,
            "status": "sanity_limit_exceeded",
            "corrections": [],
            "stats": {
                "status": "sanity_limit_exceeded",
                "total_rows": len(pre_df),
                "rows_changed": 0,
                "detected_corrections": detected_count,
                "change_percentage": (detected_count / len(pre_df) * 100),
                "timestamp": datetime.now().isoformat(),
            },
        }
    
    stats = {
        "total_rows": len(pre_df),
        "rows_changed": len(corrections),
        "change_percentage": (len(corrections) / len(pre_df) * 100) if len(pre_df) > 0 else 0,
        "timestamp": datetime.now().isoformat()
    }
    
    logger.info(f"Extracted {len(corrections)} training examples from {sheet_id}: {stats}")
    
    # Clear the cached state after processing
    clear_pre_correction_state(sheet_id)
    
    return {
        "success": True,
        "corrections": corrections,
        "stats": stats
    }


def write_training_examples_to_file(
    corrections: list[dict],
    output_path: str | Path = "data/auto_training_corrections.jsonl"
) -> Path:
    """
    Write extracted corrections to a JSONL file (one JSON object per line).
    
    This file can be converted to Excel for retraining with train.py.
    
    Args:
        corrections: List of correction examples
        output_path: Where to write the JSONL file
        
    Returns:
        Path to the written file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    def _json_default(o):
        try:
            return o.item()
        except Exception:
            return str(o)

    # Normalize strings in the correction objects to NFC and write with explicit utf-8
    def _normalize_obj(o):
        if isinstance(o, str):
            return unicodedata.normalize('NFC', o)
        if isinstance(o, dict):
            return {(_normalize_obj(k) if isinstance(k, str) else k): _normalize_obj(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_normalize_obj(x) for x in o]
        return o

    # Write bytes with explicit UTF-8 encoding to avoid any text-mode encoding mismatch
    encoded_lines: list[bytes] = []
    for correction in corrections:
        try:
            safe_corr = _normalize_obj(correction)
            # Use ASCII-safe JSON escaping to avoid corruption on readers that mis-handle UTF-8
            line = json.dumps(safe_corr, ensure_ascii=True, default=_json_default)
        except Exception:
            # Fallback to safe string conversion of the entire dict
            safe = {k: (v if isinstance(v, (str, int, float, bool, type(None))) else str(v)) for k, v in correction.items()}
            safe = _normalize_obj(safe)
            line = json.dumps(safe, ensure_ascii=True)
        encoded_lines.append((line + "\n").encode("utf-8"))

    with _AUTO_TRAINING_JSONL_LOCK:
        with open(output_path, "ab") as f:
            for encoded_line in encoded_lines:
                f.write(encoded_line)
            f.flush()
            os.fsync(f.fileno())
    
    logger.info(f"Wrote {len(corrections)} training examples to {output_path}")
    return output_path


def corrections_to_training_dataframe(
    corrections: list[dict],
    address_column: str = "Adresse",
    taxi_column: str = "Groupe Taxi"
) -> pd.DataFrame:
    """
    Convert extracted corrections into a training DataFrame suitable for ML retraining.
    
    Each correction becomes one row with all address/feature columns and the
    CORRECTED taxi assignment (which is the ground truth).
    
    Args:
        corrections: List of correction dicts from extract_training_examples_from_corrections
        address_column: Name of the address column in row_data
        taxi_column: Name of the taxi column in row_data
        
    Returns:
        DataFrame suitable for feeding into train_from_folder() or train_model_from_historique_excel()
    """
    if not corrections:
        return pd.DataFrame()
    
    # Extract the row data with corrected taxi assignment
    rows = []
    for corr in corrections:
        row = corr.get("row_data", {})
        taxi = corr.get("after")
        if taxi and row:
            row[taxi_column] = taxi  # Use corrected assignment
            rows.append(row)
    
    if not rows:
        return pd.DataFrame()
    
    return pd.DataFrame(rows)


def append_corrections_to_training_file(
    corrections: list[dict],
    output_path: str | Path = "data/training_files/auto_corrections.xlsx",
    address_column: str = "Adresse",
    taxi_column: str = "Groupe Taxi"
) -> Path:
    """
    Append extracted corrections to an existing training Excel file.
    
    This creates an incremental training set that grows as users correct the system.
    
    Args:
        corrections: List of correction examples
        output_path: Path to the Excel file to append to
        address_column: Name of the address column
        taxi_column: Name of the taxi column
        
    Returns:
        Path to the updated file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    df_corrections = corrections_to_training_dataframe(
        corrections,
        address_column=address_column,
        taxi_column=taxi_column
    )
    
    if df_corrections.empty:
        logger.warning("No valid corrections to append")
        return output_path
    
    # If file exists, append; otherwise create
    if output_path.exists():
        try:
            df_existing = pd.read_excel(output_path)
            df_combined = pd.concat([df_existing, df_corrections], ignore_index=True)
            logger.info(f"Appending {len(df_corrections)} rows to existing {output_path}")
        except Exception as e:
            logger.warning(f"Could not read existing file {output_path}: {e}; creating new")
            df_combined = df_corrections
    else:
        df_combined = df_corrections
    
    df_combined.to_excel(output_path, index=False, engine="openpyxl")
    logger.info(f"Wrote {len(df_combined)} total training examples to {output_path}")
    
    return output_path


def count_training_corrections(path: Path | None = None) -> int:
    if path is None:
        path = _get_training_corrections_path()
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def load_retrain_state(path: Path = RETRAIN_STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {
            "last_processed_count": 0,
            "last_retrain_at": None,
            "last_decision": None,
            "last_error": None,
            "last_live_accuracy": None,
            "last_candidate_accuracy": None,
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Could not read retrain state at %s, resetting state", path)
        return {
            "last_processed_count": 0,
            "last_retrain_at": None,
            "last_decision": None,
            "last_error": None,
        }


def save_retrain_state(state: dict[str, Any], path: Path = RETRAIN_STATE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _RETRAIN_STATE_LOCK:
        _atomic_write_text(path, json.dumps(state, indent=2, ensure_ascii=False))
    return path


def should_trigger_retrain(total_count: int, threshold: int, state: dict[str, Any]) -> bool:
    last_processed = int(state.get("last_processed_count", 0))
    return total_count - last_processed >= threshold


def load_corrections_from_jsonl(path: Path | None = None) -> list[dict[str, Any]]:
    if path is None:
        path = _get_training_corrections_path()
    corrections: list[dict[str, Any]] = []
    if not path.exists():
        return corrections
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    corrections.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed training correction line")
    return corrections


def write_training_dataframe_to_excel(df: pd.DataFrame, target_path: Path) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(target_path, index=False, engine="openpyxl")
    return target_path


def normalize_training_dataframe_for_historique(df: pd.DataFrame) -> pd.DataFrame:
    if "Groupe Taxi" in df.columns and "Taxi" not in df.columns:
        df = df.rename(columns={"Groupe Taxi": "Taxi"})

    ordered_columns = [col for col in HISTORIQUE_COLUMNS if col in df.columns]
    remaining_columns = [col for col in df.columns if col not in ordered_columns]
    if ordered_columns:
        return df.loc[:, ordered_columns + remaining_columns]
    return df


def build_default_holdout_dataframe() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    blocks = [
        {
            "block_id": "holdout1",
            "date": "2026-07-15",
            "groups": [
                {
                    "taxi": "1",
                    "members": [
                        {"name": "Yasmin Abdelli", "operation": "Site client", "site": "Beb Souika", "address": "Beb Souika, Tunis", "time": "09:00"},
                        {"name": "Samir Hentati", "operation": "Site client", "site": "Beb Souika", "address": "Bab Souika, Tunis", "time": "09:00"},
                    ],
                },
                {
                    "taxi": "2",
                    "members": [
                        {"name": "Ines Ghribi", "operation": "Visite client", "site": "Route Raoued", "address": "Route Raoued, Ariana", "time": "09:00"},
                        {"name": "Oussama Jaziri", "operation": "Visite client", "site": "Nkhilette", "address": "Nkhilette, Ariana", "time": "09:00"},
                    ],
                },
            ],
        },
        {
            "block_id": "holdout2",
            "date": "2026-07-15",
            "groups": [
                {
                    "taxi": "1",
                    "members": [
                        {"name": "Amal Selmi", "operation": "Retour hôtel", "site": "Ariana Centre", "address": "Ariana Centre, Ariana", "time": "10:00"},
                        {"name": "Nabil Toumi", "operation": "Retour hôtel", "site": "Ghazela", "address": "Ghazela, Ariana", "time": "10:00"},
                    ],
                },
                {
                    "taxi": "2",
                    "members": [
                        {"name": "Wael Ben Ali", "operation": "Aéroport", "site": "Marsa", "address": "Marsa, La Marsa", "time": "10:00"},
                        {"name": "Karima Aouadi", "operation": "Aéroport", "site": "Sidi Bou Said", "address": "Sidi Bou Said, Tunis", "time": "10:00"},
                    ],
                },
            ],
        },
    ]
    for block in blocks:
        for group in block["groups"]:
            for member in group["members"]:
                rows.append(
                    {
                        "Date": block["date"],
                        "Matricule": f"H{block['block_id']}{group['taxi']}{len(rows)+1}",
                        "Nom - Prénom": member["name"],
                        "Opération": member["operation"],
                        "Site": member["site"],
                        "Adresse": member["address"],
                        "Heure d'arrivée": member["time"],
                        "Taxi": group["taxi"],
                        "SourceSheet": f"Holdout_{block['block_id']}",
                        "BlockID": f"Holdout_{block['block_id']}",
                    }
                )
    return pd.DataFrame(rows)


def evaluate_historique_model_on_dataframe(model: Any, df: pd.DataFrame) -> dict[str, Any]:
    if "TrainingTaxiGroup" not in df.columns and "Taxi" in df.columns:
        df = df.copy()
        df["TrainingTaxiGroup"] = df["Taxi"].astype(str)

    x, y = prepare_historique_pairwise_examples(df)
    if x.shape[0] == 0:
        raise ValueError("No valid pairwise examples could be created from holdout data.")
    predictions = model.predict(x)
    return {
        "example_count": int(len(y)),
        "accuracy": float(accuracy_score(y, predictions)),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_file_atomically(
    source: Path,
    destination: Path,
    active_model_path: Path,
) -> None:
    ensure_model_write_allowed(
        destination,
        active_model_path=active_model_path,
        approved_promotion=True,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, dir=destination.parent, suffix=".tmp") as temp_file:
            temp_path = Path(temp_file.name)
        shutil.copy2(source, temp_path)
        os.replace(temp_path, destination)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _append_promotion_log(log_path: Path, entry: dict[str, Any]) -> None:
    existing = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    _atomic_write_text(
        log_path,
        existing + json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n",
    )


def promote_candidate_model(
    active_model_path: Path,
    candidate_model_path: Path,
    *,
    approved: bool = False,
    approved_by: str = "",
    candidate_version: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> None:
    """Promote a candidate only after explicit, configured human approval."""
    active_path = Path(active_model_path)
    candidate_path = Path(candidate_model_path)
    if not approved:
        raise PermissionError("Promotion requires explicit human approval (approved=True or CLI --approve).")
    if not approved_by.strip():
        raise ValueError("approved_by must identify the human approving this promotion.")
    if metrics is None or not isinstance(metrics, dict):
        raise ValueError("Promotion requires candidate evaluation/training metrics to record.")
    ensure_model_write_allowed(
        active_path,
        active_model_path=active_path,
        approved_promotion=True,
    )
    if not active_path.is_file():
        raise FileNotFoundError(f"Active model not found: {active_path}")
    if not candidate_path.is_file():
        raise FileNotFoundError(f"Candidate model not found: {candidate_path}")

    timestamp = datetime.now(timezone.utc).isoformat()
    version = candidate_version or _sha256_file(candidate_path)
    backup_dir = active_path.parent / "rollback"
    backup_path = backup_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{_sha256_file(active_path)[:12]}.pkl"
    log_path = active_path.parent / "promotion_log.jsonl"
    entry = {
        "action": "promote",
        "approved_by": approved_by.strip(),
        "candidate_version": version,
        "timestamp": timestamp,
        "metrics": metrics,
    }
    json.dumps(entry, ensure_ascii=False)

    with _MODEL_PROMOTION_LOCK:
        previous_hash = _sha256_file(active_path)
        _copy_file_atomically(active_path, backup_path, active_path)
        try:
            _copy_file_atomically(candidate_path, active_path, active_path)
            _append_promotion_log(log_path, entry)
        except Exception:
            if _sha256_file(active_path) != previous_hash:
                restore_path = active_path.parent / f".{active_path.name}.restore"
                _copy_file_atomically(backup_path, restore_path, active_path)
                ensure_model_write_allowed(
                    active_path,
                    active_model_path=active_path,
                    approved_promotion=True,
                )
                os.replace(restore_path, active_path)
            raise


def rollback_active_model(
    active_model_path: Path = DEFAULT_MODEL_PATH,
    *,
    approved: bool = False,
    approved_by: str = "",
) -> Path:
    """Restore the most recent saved active model after explicit approval."""
    active_path = Path(active_model_path)
    if not approved:
        raise PermissionError("Rollback requires explicit human approval (approved=True or CLI --approve).")
    if not approved_by.strip():
        raise ValueError("approved_by must identify the human approving this rollback.")
    ensure_model_write_allowed(
        active_path,
        active_model_path=active_path,
        approved_promotion=True,
    )
    backups = sorted((active_path.parent / "rollback").glob("*.pkl"))
    if not backups:
        raise FileNotFoundError(f"No rollback model is available under {active_path.parent / 'rollback'}.")
    if not active_path.is_file():
        raise FileNotFoundError(f"Active model not found: {active_path}")

    backup_path = backups[-1]
    timestamp = datetime.now(timezone.utc).isoformat()
    entry = {
        "action": "rollback",
        "approved_by": approved_by.strip(),
        "candidate_version": backup_path.stem,
        "timestamp": timestamp,
        "metrics": {"restored_from": str(backup_path)},
    }
    previous_path = active_path.parent / "rollback" / (
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_before_rollback.pkl"
    )
    log_path = active_path.parent / "promotion_log.jsonl"
    with _MODEL_PROMOTION_LOCK:
        previous_hash = _sha256_file(active_path)
        _copy_file_atomically(active_path, previous_path, active_path)
        try:
            _copy_file_atomically(backup_path, active_path, active_path)
            _append_promotion_log(log_path, entry)
        except Exception:
            if _sha256_file(active_path) != previous_hash:
                restore_path = active_path.parent / f".{active_path.name}.restore"
                _copy_file_atomically(previous_path, restore_path, active_path)
                os.replace(restore_path, active_path)
            raise
    return backup_path


def run_retraining_pipeline(threshold: int) -> dict[str, Any]:
    total_count = count_training_corrections()
    state = load_retrain_state()
    trigger = should_trigger_retrain(total_count, threshold, state)
    if not trigger:
        return {
            "triggered": False,
            "reason": "threshold_not_reached",
            "total_count": total_count,
            "last_processed_count": state.get("last_processed_count", 0),
        }

    corrections = load_corrections_from_jsonl()
    if not corrections:
        state.update(
            last_processed_count=total_count,
            last_retrain_at=datetime.now().isoformat(),
            last_decision="no_corrections",
            last_error=None,
        )
        save_retrain_state(state)
        return {
            "triggered": True,
            "success": False,
            "reason": "no_corrections_to_train",
            "total_count": total_count,
        }

    training_df = corrections_to_training_dataframe(corrections)
    if training_df.empty:
        state.update(
            last_processed_count=total_count,
            last_retrain_at=datetime.now().isoformat(),
            last_decision="empty_training",
            last_error=None,
        )
        save_retrain_state(state)
        return {
            "triggered": True,
            "success": False,
            "reason": "empty_training_dataframe",
            "total_count": total_count,
        }

    training_df = normalize_training_dataframe_for_historique(training_df)

    CANDIDATE_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as temp_dir:
        training_file = Path(temp_dir) / "auto_training.xlsx"
        write_training_dataframe_to_excel(training_df, training_file)
        try:
            candidate_metrics = train_model_from_historique_excel(str(training_file), str(CANDIDATE_MODEL_DIR))
        except Exception as exc:
            error_text = str(exc)
            logger.exception("Candidate training failed")
            state.update(
                last_processed_count=total_count,
                last_retrain_at=datetime.now().isoformat(),
                last_decision="training_failed",
                last_error=error_text,
            )
            save_retrain_state(state)
            return {
                "triggered": True,
                "success": False,
                "reason": "training_failed",
                "error": error_text,
                "total_count": total_count,
            }

    candidate_model = load_model(CANDIDATE_MODEL_PATH)
    live_model = load_model(DEFAULT_MODEL_PATH)
    if candidate_model is None or live_model is None:
        error_text = "Could not load live or candidate model after training"
        state.update(
            last_processed_count=total_count,
            last_retrain_at=datetime.now().isoformat(),
            last_decision="load_failed",
            last_error=error_text,
        )
        save_retrain_state(state)
        return {
            "triggered": True,
            "success": False,
            "reason": "load_failed",
            "error": error_text,
            "total_count": total_count,
        }

    holdout_df = build_default_holdout_dataframe()
    live_results = evaluate_historique_model_on_dataframe(live_model, holdout_df)
    candidate_results = evaluate_historique_model_on_dataframe(candidate_model, holdout_df)

    evaluation_report = {
        "timestamp": datetime.now().isoformat(),
        "decision": None,
        "live_accuracy": live_results["accuracy"],
        "candidate_accuracy": candidate_results["accuracy"],
        "live_accuracy_repr": repr(live_results["accuracy"]),
        "candidate_accuracy_repr": repr(candidate_results["accuracy"]),
        "candidate_training_metrics": candidate_metrics,
        "holdout_example_count": live_results.get("example_count"),
        "total_corrections": total_count,
    }

    decision = (
        "candidate_ready_for_review"
        if candidate_results["accuracy"] > live_results["accuracy"]
        else "candidate_not_better"
    )

    evaluation_report["decision"] = decision
    try:
        EVALUATION_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVALUATION_REPORT_PATH.write_text(json.dumps(evaluation_report, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not write evaluation report to %s: %s", EVALUATION_REPORT_PATH, exc)

    state.update(
        last_processed_count=total_count,
        last_retrain_at=datetime.now().isoformat(),
        last_decision=decision,
        last_error=None,
        last_live_accuracy=live_results["accuracy"],
        last_candidate_accuracy=candidate_results["accuracy"],
    )
    save_retrain_state(state)

    return {
        "triggered": True,
        "success": True,
        "decision": decision,
        "live_accuracy": live_results["accuracy"],
        "candidate_accuracy": candidate_results["accuracy"],
        "candidate_training_metrics": candidate_metrics,
        "total_count": total_count,
    }
