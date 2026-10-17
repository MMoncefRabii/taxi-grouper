"""Pairwise ML model for taxi grouping assistance."""

from __future__ import annotations

import json
import logging
import random
import re
from datetime import date, datetime, time
from itertools import combinations
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split

from ..config import DEFAULT_CANDIDATE_MODEL_PATH, DEFAULT_CONFIG_PATH, DEFAULT_MODEL_PATH, UNKNOWN_ZONE
from .model_storage import ensure_model_write_allowed, save_model_artifact, write_model_metadata
from .preprocessing import ColumnMap, detect_columns, load_excel
from .zones import detect_zone, normalize_address, normalize_text, zones_are_compatible


HISTORIQUE_COLUMNS = [
    "Date",
    "Matricule",
    "Nom - Prénom",
    "Opération",
    "Site",
    "Adresse",
    "Heure d'arrivée",
    "Taxi",
]

HISTORIQUE_FEATURE_NAMES = [
    "same_exact_address",
    "address_similarity_score",
    "same_zone",
    "compatible_zone",
    "same_operation",
    "same_site",
    "same_time",
    "same_date",
    "same_block",
    "same_city_or_commune",
    "same_street_keyword",
    "fuzzy_address_score",
    "zone_distance_score",
]

FEATURE_NAMES = [
    "same_zone",
    "compatible_zone",
    "same_exact_address",
    "address_similarity_score",
    "same_operation",
    "same_site",
    "same_time",
    "same_type_course",
    "same_client",
    "zone_distance_score",
    "commune_match",
    "street_keyword_match",
    "fuzzy_address_score",
    "same_neighborhood",
    "historical_frequency_score",
]


def _clean_broken_text(value: object) -> str:
    text = "" if value is None or pd.isna(value) else str(value)
    replacements = {
        "Ă©": "e",
        "Ă¨": "e",
        "ĂŞ": "e",
        "Ă ": "a",
        "Â": " ",
        "ŕ": "a",
        "č": "e",
        "ď": "i",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text


def _is_historique_header_row(values: list[object]) -> bool:
    normalized = [normalize_text(_clean_broken_text(value)) for value in values[: len(HISTORIQUE_COLUMNS)]]
    expected = [normalize_text(value) for value in HISTORIQUE_COLUMNS]
    return normalized == expected


def _format_date(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return str(value).strip()
    return parsed.date().isoformat()


def _format_time(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, (int, float)) and 0 <= float(value) < 1:
        minutes = int(round(float(value) * 24 * 60)) % (24 * 60)
        return f"{minutes // 60:02d}:{minutes % 60:02d}"
    text = str(value).strip()
    time_match = re.search(r"(\d{1,2})[:hH](\d{2})", text)
    if time_match:
        return f"{int(time_match.group(1)):02d}:{int(time_match.group(2)):02d}"
    parsed = pd.to_datetime(value, errors="coerce")
    if not pd.isna(parsed):
        return parsed.strftime("%H:%M")
    return str(value).strip()


def load_historique_excel(file_path: str | Path) -> pd.DataFrame:
    """Load Historique.xlsx multi-sheet data, removing repeated headers and filling taxi groups per block."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Historical training file not found: {path}")

    sheets = pd.read_excel(path, sheet_name=None, header=None)
    cleaned_frames: list[pd.DataFrame] = []

    for sheet_name, raw in sheets.items():
        current_block = -1
        current_taxi: str | None = None
        rows: list[dict[str, Any]] = []

        for raw_index, raw_row in raw.iterrows():
            values = raw_row.iloc[: len(HISTORIQUE_COLUMNS)].tolist()
            if _is_historique_header_row(values):
                current_block += 1
                current_taxi = None
                continue
            if current_block < 0 or all(value is None or pd.isna(value) or str(value).strip() == "" for value in values):
                continue

            record = dict(zip(HISTORIQUE_COLUMNS, values))
            taxi_value = record.get("Taxi")
            if taxi_value is not None and not pd.isna(taxi_value) and str(taxi_value).strip():
                current_taxi = str(taxi_value).strip()
            if not current_taxi:
                continue

            for text_col in ["Nom - Prénom", "Opération", "Site", "Adresse"]:
                record[text_col] = _clean_broken_text(record.get(text_col))
            record["Date"] = _format_date(record.get("Date"))
            record["Heure d'arrivée"] = _format_time(record.get("Heure d'arrivée"))
            record["TrainingTaxiGroup"] = current_taxi
            record["BlockID"] = f"{sheet_name}_{current_block}"
            record["SourceSheet"] = sheet_name
            record["SourceRow"] = int(raw_index) + 1
            rows.append(record)

        if rows:
            cleaned_frames.append(pd.DataFrame(rows))

    if not cleaned_frames:
        raise ValueError("No valid agent rows were found in the historical workbook.")

    result = pd.concat(cleaned_frames, ignore_index=True)
    address_cache: dict[str, tuple[str, str]] = {}

    def cached_address_info(address: object) -> tuple[str, str]:
        key = str(address)
        if key not in address_cache:
            normalized = normalize_address(key)
            address_cache[key] = (detect_zone(normalized).zone_code, normalized)
        return address_cache[key]

    address_info = result["Adresse"].apply(cached_address_info)
    result["_zone"] = address_info.apply(lambda item: item[0])
    result["_normalized_address"] = address_info.apply(lambda item: item[1])
    return result


def _historique_features(row_a: pd.Series, row_b: pd.Series) -> list[float]:
    addr_a = str(row_a.get("_normalized_address") or normalize_address(row_a.get("Adresse", "")))
    addr_b = str(row_b.get("_normalized_address") or normalize_address(row_b.get("Adresse", "")))
    tokens_a = set(addr_a.split())
    tokens_b = set(addr_b.split())
    overlap = len(tokens_a & tokens_b) / max(len(tokens_a | tokens_b), 1)
    fuzzy_score = fuzz.token_set_ratio(addr_a, addr_b) / 100
    zone_a = str(row_a.get("_zone", "UNKNOWN"))
    zone_b = str(row_b.get("_zone", "UNKNOWN"))
    return [
        float(addr_a == addr_b and bool(addr_a)),
        fuzzy_score,
        float(zone_a == zone_b and zone_a != UNKNOWN_ZONE),
        float(zones_are_compatible(zone_a, zone_b)),
        float(normalize_text(row_a.get("Opération", "")) == normalize_text(row_b.get("Opération", ""))),
        float(normalize_text(row_a.get("Site", "")) == normalize_text(row_b.get("Site", ""))),
        float(str(row_a.get("Heure d'arrivée", "")) == str(row_b.get("Heure d'arrivée", ""))),
        float(str(row_a.get("Date", "")) == str(row_b.get("Date", ""))),
        float(str(row_a.get("BlockID", "")) == str(row_b.get("BlockID", ""))),
        float(overlap >= 0.25),
        overlap,
        fuzzy_score,
        1.0 if zone_a == zone_b else (0.65 if zones_are_compatible(zone_a, zone_b) else 0.0),
    ]


def prepare_historique_pairwise_examples(df: pd.DataFrame, negative_multiplier: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    features: list[list[float]] = []
    labels: list[int] = []
    group_cols = ["SourceSheet", "BlockID", "Date", "Heure d'arrivée"]
    rng = random.Random(42)

    for _, block in df.groupby(group_cols, dropna=False):
        block = block.reset_index(drop=True)
        if len(block) < 2:
            continue
        positives: list[tuple[int, int]] = []
        negatives: list[tuple[int, int]] = []
        for i, j in combinations(block.index, 2):
            row_a = block.loc[i]
            row_b = block.loc[j]
            if str(row_a["TrainingTaxiGroup"]) == str(row_b["TrainingTaxiGroup"]):
                positives.append((i, j))
            else:
                negatives.append((i, j))

        if not positives and not negatives:
            continue
        max_negatives = len(negatives) if negative_multiplier is None else max(len(positives) * negative_multiplier, min(len(negatives), 20))
        if negative_multiplier is not None and len(negatives) > max_negatives:
            negatives = rng.sample(negatives, max_negatives)

        for i, j in positives:
            features.append(_historique_features(block.loc[i], block.loc[j]))
            labels.append(1)
        for i, j in negatives:
            features.append(_historique_features(block.loc[i], block.loc[j]))
            labels.append(0)

    if not features:
        raise ValueError("No valid pairwise examples could be generated from the historical workbook.")
    return np.asarray(features, dtype=float), np.asarray(labels, dtype=int)


def train_model_from_historique_excel(
    file_path: str,
    output_dir: str | Path = DEFAULT_CANDIDATE_MODEL_PATH.parent,
) -> dict:
    """
    Train the taxi grouping model from a historical Excel file that follows
    the Historique.xlsx structure.

    The file can contain several monthly sheets.
    Repeated header rows must be removed.
    Taxi values must be forward-filled inside each dispatch block.
    Pairwise examples must be generated inside each date/time/block.
    The trained model and training report must be saved.

    Returns a dictionary with training metrics.
    """
    path = Path(file_path)
    output = Path(output_dir)
    ensure_model_write_allowed(output)
    cleaned = load_historique_excel(path)
    x_all, y_all = prepare_historique_pairwise_examples(cleaned)

    positive_pairs = int(y_all.sum())
    negative_pairs = int(len(y_all) - positive_pairs)
    if len(set(y_all.tolist())) < 2:
        raise ValueError("Historical file must produce both positive and negative taxi pair examples.")

    x_train, x_test, y_train, y_test = train_test_split(
        x_all,
        y_all,
        test_size=0.25,
        random_state=42,
        stratify=y_all,
    )
    model = RandomForestClassifier(n_estimators=250, random_state=42, class_weight="balanced", min_samples_leaf=1)
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)

    report = {
        "accuracy": float(accuracy_score(y_test, predictions)),
        "precision": float(precision_score(y_test, predictions, zero_division=0)),
        "recall": float(recall_score(y_test, predictions, zero_division=0)),
        "f1_score": float(f1_score(y_test, predictions, zero_division=0)),
        "number_of_agents": int(len(cleaned)),
        "number_of_pair_examples": int(len(y_all)),
        "positive_pairs": positive_pairs,
        "negative_pairs": negative_pairs,
        "training_file_name": path.name,
        "training_date": datetime.now().isoformat(timespec="seconds"),
        "model": "RandomForestClassifier",
        "features": HISTORIQUE_FEATURE_NAMES,
        "sheets": sorted(cleaned["SourceSheet"].unique().tolist()),
    }

    save_model_artifact(model, output, DEFAULT_MODEL_PATH.name)
    write_model_metadata(output / "training_report.json", report)
    return report


def train_candidate_from_historique_excel(file_path: str | Path) -> dict[str, Any]:
    """Train the packaged operator workflow's candidate without activating it."""
    return train_model_from_historique_excel(
        str(file_path),
        DEFAULT_CANDIDATE_MODEL_PATH.parent,
    )


def _value(row: pd.Series, col: str | None) -> str:
    if not col or col not in row:
        return ""
    value = row[col]
    if pd.isna(value):
        return ""
    return normalize_text(value)


def pair_features(row_a: pd.Series, row_b: pd.Series, columns: ColumnMap, historical_frequency: float = 0.0) -> list[float]:
    addr_a = normalize_address(row_a.get(columns.address, ""))
    addr_b = normalize_address(row_b.get(columns.address, ""))
    zone_a = row_a.get("_zone") or detect_zone(addr_a).zone_code
    zone_b = row_b.get("_zone") or detect_zone(addr_b).zone_code
    tokens_a = set(addr_a.split())
    tokens_b = set(addr_b.split())
    token_overlap = len(tokens_a & tokens_b) / max(len(tokens_a | tokens_b), 1)
    fuzzy_score = fuzz.token_set_ratio(addr_a, addr_b) / 100
    return [
        float(zone_a == zone_b and zone_a != UNKNOWN_ZONE),
        float(zones_are_compatible(str(zone_a), str(zone_b))),
        float(addr_a == addr_b and bool(addr_a)),
        fuzzy_score,
        float(_value(row_a, columns.operation) == _value(row_b, columns.operation) and bool(_value(row_a, columns.operation))),
        float(_value(row_a, columns.site) == _value(row_b, columns.site) and bool(_value(row_a, columns.site))),
        float(_value(row_a, columns.time) == _value(row_b, columns.time) and bool(_value(row_a, columns.time))),
        float(_value(row_a, columns.type_course) == _value(row_b, columns.type_course) and bool(_value(row_a, columns.type_course))),
        float(_value(row_a, columns.client) == _value(row_b, columns.client) and bool(_value(row_a, columns.client))),
        1.0 if zone_a == zone_b else (0.65 if zones_are_compatible(str(zone_a), str(zone_b)) else 0.0),
        float(token_overlap > 0),
        token_overlap,
        fuzzy_score,
        float(token_overlap >= 0.4 or fuzzy_score >= 0.82),
        float(historical_frequency),
    ]


def prepare_training_examples(df: pd.DataFrame, columns: ColumnMap) -> tuple[np.ndarray, np.ndarray]:
    work = df.copy()
    detections = work[columns.address].apply(detect_zone)
    work["_zone"] = detections.apply(lambda match: match.zone_code)

    features: list[list[float]] = []
    labels: list[int] = []
    for i, j in combinations(work.index, 2):
        taxi_i = str(work.at[i, columns.taxi]).strip()
        taxi_j = str(work.at[j, columns.taxi]).strip()
        if not taxi_i or not taxi_j or taxi_i.lower() == "nan" or taxi_j.lower() == "nan":
            continue
        features.append(pair_features(work.loc[i], work.loc[j], columns))
        labels.append(int(taxi_i == taxi_j))

    if not features:
        raise ValueError("No valid pairwise training examples could be created.")
    return np.asarray(features, dtype=float), np.asarray(labels, dtype=int)


def train_from_folder(
    data_dir: str | Path,
    output_dir: str | Path = DEFAULT_CANDIDATE_MODEL_PATH.parent,
) -> dict[str, Any]:
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    ensure_model_write_allowed(output_dir)
    files = sorted([*data_dir.glob("*.xlsx"), *data_dir.glob("*.xls")])
    if not files:
        raise FileNotFoundError(f"No Excel training files found in {data_dir}")

    all_x: list[np.ndarray] = []
    all_y: list[np.ndarray] = []
    for file in files:
        df = load_excel(file)
        columns = detect_columns(df, require_taxi=True)
        x, y = prepare_training_examples(df, columns)
        all_x.append(x)
        all_y.append(y)

    x_all = np.vstack(all_x)
    y_all = np.concatenate(all_y)
    if len(set(y_all.tolist())) < 2:
        raise ValueError("Training data must contain both positive and negative taxi pair examples.")

    x_train, x_test, y_train, y_test = train_test_split(x_all, y_all, test_size=0.25, random_state=42, stratify=y_all)
    model = RandomForestClassifier(n_estimators=200, random_state=42, class_weight="balanced", min_samples_leaf=1)
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)

    metrics = {
        "accuracy": float(accuracy_score(y_test, predictions)),
        "precision": float(precision_score(y_test, predictions, zero_division=0)),
        "recall": float(recall_score(y_test, predictions, zero_division=0)),
        "f1": float(f1_score(y_test, predictions, zero_division=0)),
        "files": [str(file) for file in files],
        "features": FEATURE_NAMES,
        "model": "RandomForestClassifier",
    }

    save_model_artifact(model, output_dir, DEFAULT_MODEL_PATH.name)
    write_model_metadata(output_dir / DEFAULT_CONFIG_PATH.name, metrics)
    return metrics


_logger = logging.getLogger(__name__)

def load_model(model_path: str | Path = DEFAULT_MODEL_PATH) -> Any | None:
    path = Path(model_path)
    if not path.exists():
        return None
    model = joblib.load(path)
    # Try to load a training/config report from the same directory to learn feature names
    metadata_candidates: list[tuple[Path, list[str], dict[str, Any]]] = []
    try:
        for candidate in [path.with_name(DEFAULT_CONFIG_PATH.name), path.parent / "training_report.json"]:
            if candidate.exists():
                try:
                    metrics = json.loads(candidate.read_text(encoding="utf-8"))
                    features = metrics.get("features")
                    if isinstance(features, list):
                        metadata_candidates.append((candidate, list(features), metrics))
                except Exception:
                    # Non-fatal: ignore malformed metrics file
                    pass
    except Exception:
        pass

    if metadata_candidates:
        chosen_features: list[str] | None = None
        chosen_metrics: dict[str, Any] | None = None
        n_features = getattr(model, "n_features_in_", None)
        if n_features is not None:
            matching = [item for item in metadata_candidates if len(item[1]) == n_features]
            if len(matching) == 1:
                chosen_features = matching[0][1]
                chosen_metrics = matching[0][2]
            elif len(matching) > 1:
                distinct_sets = {tuple(item[1]) for item in matching}
                if len(distinct_sets) == 1:
                    chosen_features = matching[0][1]
                    chosen_metrics = matching[0][2]
                else:
                    raise ValueError(
                        f"Multiple metadata sources match model.n_features_in_={n_features} but disagree on feature lists: "
                        f"{[str(item[0]) for item in matching]}"
                    )
            elif len(metadata_candidates) == 1:
                candidate_path, candidate_features, _ = metadata_candidates[0]
                raise ValueError(
                    f"Metadata source {candidate_path} lists {len(candidate_features)} features, "
                    f"but model.n_features_in_={n_features}. Rejecting ambiguous metadata instead of guessing."
                )
            else:
                raise ValueError(
                    f"No metadata sources match model.n_features_in_={n_features}. "
                    f"Available candidate lengths: {[len(item[1]) for item in metadata_candidates]}"
                )
        else:
            chosen_features = metadata_candidates[0][1]
            chosen_metrics = metadata_candidates[0][2]

        if chosen_features is not None:
            setattr(model, "_feature_names", chosen_features)
        if chosen_metrics and "model" in chosen_metrics:
            setattr(model, "_model_name", chosen_metrics.get("model"))

    if not hasattr(model, "_feature_names"):
        _logger.warning(
            "Loaded legacy ML model %s without explicit _feature_names metadata; using legacy feature-count fallback logic. Re-save the model with explicit metadata to avoid fallback behavior.",
            path,
        )
    return model


def score_pairs(model: Any | None, rows_a: list[pd.Series], rows_b: list[pd.Series], columns: ColumnMap) -> np.ndarray:
    if model is None:
        return np.zeros(len(rows_a), dtype=float)
    # Prefer explicit feature list saved with the model; fallback to sklearn's n_features_in_
    feature_names = getattr(model, "_feature_names", None)
    if feature_names is None:
        expected_features = getattr(model, "n_features_in_", len(FEATURE_NAMES))
        use_historique = expected_features == len(HISTORIQUE_FEATURE_NAMES)
    else:
        use_historique = feature_names == HISTORIQUE_FEATURE_NAMES
    if use_historique:
        x = np.asarray(
            [
                _historique_features(_row_to_historique_shape(row_a, columns), _row_to_historique_shape(row_b, columns))
                for row_a, row_b in zip(rows_a, rows_b)
            ],
            dtype=float,
        )
    else:
        x = np.asarray(
            [pair_features(row_a, row_b, columns) for row_a, row_b in zip(rows_a, rows_b)],
            dtype=float,
        )
    if hasattr(model, "predict_proba"):
        return model.predict_proba(x)[:, 1].astype(float)
    return model.predict(x).astype(float)


def score_pair(model: Any | None, row_a: pd.Series, row_b: pd.Series, columns: ColumnMap) -> float:
    if model is None:
        return 0.0
    feature_names = getattr(model, "_feature_names", None)
    if feature_names is None:
        expected_features = getattr(model, "n_features_in_", len(FEATURE_NAMES))
        use_historique = expected_features == len(HISTORIQUE_FEATURE_NAMES)
    else:
        use_historique = feature_names == HISTORIQUE_FEATURE_NAMES
    if use_historique:
        hist_a = _row_to_historique_shape(row_a, columns)
        hist_b = _row_to_historique_shape(row_b, columns)
        x = np.asarray([_historique_features(hist_a, hist_b)], dtype=float)
    else:
        x = np.asarray([pair_features(row_a, row_b, columns)], dtype=float)
    if hasattr(model, "predict_proba"):
        return float(model.predict_proba(x)[0][1])
    return float(model.predict(x)[0])


def _row_to_historique_shape(row: pd.Series, columns: ColumnMap) -> pd.Series:
    data = {
        "Date": row.get("Date", ""),
        "Adresse": row.get(columns.address, ""),
        "Opération": row.get(columns.operation, ""),
        "Site": row.get(columns.site, ""),
        "Heure d'arrivée": row.get(columns.time, ""),
        "BlockID": row.get("BlockID", ""),
        "_zone": row.get("_zone") or row.get("Zone") or detect_zone(row.get(columns.address, "")).zone_code,
        "_normalized_address": row.get("_normalized_address") or row.get("Normalized Address") or normalize_address(row.get(columns.address, "")),
    }
    return pd.Series(data)
