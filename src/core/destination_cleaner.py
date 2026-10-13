"""Destination cleaning, detection, and correction learning."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
from rapidfuzz import fuzz, process
from unidecode import unidecode

from ..config import DATA_DIR, UNKNOWN_ZONE
from .destination_detector import DESTINATION_ALIASES

ALIASES_PATH = DATA_DIR / "destination_aliases.json"
UNKNOWN_DESTINATIONS_PATH = DATA_DIR / "unknown_destinations.csv"

GENERIC_WORDS = {
    "rue",
    "avenue",
    "av",
    "route",
    "rt",
    "cite",
    "cité",
    "residence",
    "résidence",
    "immeuble",
    "imm",
    "bloc",
    "num",
    "numero",
    "n",
    "n°",
    "pres",
    "près",
    "en",
    "face",
    "derriere",
    "derrière",
    "devant",
    "a",
    "à",
    "cote",
    "côté",
    "lot",
    "lotissement",
    "la",
    "le",
    "el",
}

NOISE_PHRASES = [
    "en face",
    "a cote",
    "à côté",
    "pres de",
    "près de",
]


def normalize_basic_text(text: object) -> str:
    value = "" if text is None else str(text)
    replacements = {
        "Ä‚Â©": "e",
        "Ä‚Â¨": "e",
        "Ä‚Åž": "e",
        "Ä‚ ": "a",
        "Ã‚": " ",
        "Å•": "a",
        "Ä": "e",
    }
    for bad, good in replacements.items():
        value = value.replace(bad, good)
    value = unidecode(value).lower()
    value = value.replace("-", " ")
    value = re.sub(r"[^\w\s]", " ", value)
    value = re.sub(r"\blac\s*(\d)\b", r"lac \1", value)
    return re.sub(r"\s+", " ", value).strip()


def clean_destination_text(text: str) -> str:
    """
    Clean a raw address or destination text.
    Returns a normalized string used for destination detection.
    """
    cleaned = normalize_basic_text(text)
    for phrase in NOISE_PHRASES:
        cleaned = re.sub(rf"\b{re.escape(normalize_basic_text(phrase))}\b", " ", cleaned)
    cleaned = repair_broken_words(cleaned, _known_alias_texts())
    tokens = [token for token in cleaned.split() if token not in _normalized_generic_words()]
    return re.sub(r"\s+", " ", " ".join(tokens)).strip()


def repair_broken_words(text: str, known_aliases: list[str]) -> str:
    """Try to repair badly spaced destination names using known aliases."""
    normalized = normalize_basic_text(text)
    compact_text = normalized.replace(" ", "")
    if not compact_text:
        return normalized

    normalized_aliases = {normalize_basic_text(alias) for alias in known_aliases}
    for alias in sorted(normalized_aliases, key=lambda value: (value.replace(" ", ""), value.count(" "), -len(value))):
        alias_compact = alias.replace(" ", "")
        if alias_compact and compact_text == alias_compact:
            return alias

    return normalized


def detect_clean_destination(raw_address: str) -> dict[str, Any]:
    """
    Detect the real destination and zone from a raw address.
    """
    original = "" if raw_address is None else str(raw_address)
    cleaned = clean_destination_text(original)
    normalized = normalize_basic_text(original)
    search_texts = [text for text in [normalized, normalized.replace(" ", ""), cleaned, cleaned.replace(" ", "")] if text]
    if not search_texts:
        return _unknown_result(original, cleaned)

    aliases = _alias_index()
    lookup = {alias: payload for alias, payload in aliases.items()}

    for text in search_texts:
        if text in lookup:
            return _valid_result(original, cleaned, lookup[text], text, 100, "exact")

    for alias, payload in aliases.items():
        if any(alias and re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text) for text in search_texts):
            return _valid_result(original, cleaned, payload, alias, 100, "substring")

    choices = list(aliases.keys())
    best = _best_fuzzy_match(cleaned or normalized, choices)
    if best:
        alias, score = best
        payload = lookup[alias]
        if score >= 85:
            return _valid_result(original, cleaned, payload, alias, score, "fuzzy")
        if score >= 70:
            return _manual_result(original, cleaned, payload, alias, score, "fuzzy")

    return _unknown_result(original, cleaned)


def add_clean_destination_columns(df: pd.DataFrame, address_col: str, save_unknown: bool = False) -> pd.DataFrame:
    """Add internal cleaned destination columns used by dispatch grouping.
    
    Args:
        df: Input DataFrame with raw addresses
        address_col: Column name containing addresses
        save_unknown: If True, write unknown addresses to CSV (non-blocking on error)
    
    Optimization: Deduplicates addresses before detection (1 detection per unique address, not per row).
    """
    result = df.copy()
    
    # Vectorized detection: deduplicate addresses, detect once per unique address, then map back
    # Filter out NaN addresses
    valid_addresses = result[address_col].dropna()
    unique_addresses = valid_addresses.unique()
    
    # Cache detections for each unique address
    detection_cache = {addr: detect_clean_destination(addr) for addr in unique_addresses}
    
    # Map cached results back to all rows (NaN stays NaN)
    detections = result[address_col].map(detection_cache)
    
    # Extract fields from cached detections into columns
    # For NaN/unmapped rows, provide safe defaults
    result["CleanAddress"] = detections.apply(
        lambda item: item.get("cleaned_address", "") if isinstance(item, dict) else ""
    )
    result["DetectedDestination"] = detections.apply(
        lambda item: item.get("detected_destination", UNKNOWN_ZONE) if isinstance(item, dict) else UNKNOWN_ZONE
    )
    result["DestinationZone"] = detections.apply(
        lambda item: item.get("zone", UNKNOWN_ZONE) if isinstance(item, dict) else UNKNOWN_ZONE
    )
    result["Zone"] = result["DestinationZone"]
    result["MatchedAlias"] = detections.apply(
        lambda item: (item.get("matched_alias") or "") if isinstance(item, dict) else ""
    )
    result["Matched Alias"] = result["MatchedAlias"]
    result["DestinationScore"] = detections.apply(
        lambda item: float(item.get("similarity_score", 0.0)) if isinstance(item, dict) else 0.0
    )
    result["DestinationConfidence"] = result["DestinationScore"]
    result["Confidence"] = result["DestinationScore"]
    result["DestinationStatus"] = detections.apply(
        lambda item: item.get("validation_status", "unknown") if isinstance(item, dict) else "unknown"
    )
    result["DetectionMethod"] = detections.apply(
        lambda item: item.get("method", "unknown") if isinstance(item, dict) else "unknown"
    )
    result["NeedsManualValidation"] = result["DestinationStatus"].isin(["unknown", "needs_manual_validation"])
    result["NeedsManualReview"] = result["NeedsManualValidation"]
    result["Normalized Address"] = result["CleanAddress"]
    
    # Write unknown destinations to CSV for manual review (optional, non-blocking)
    if save_unknown:
        save_unknown_destinations(result)
    
    return result


def validate_cleaned_destinations(df: pd.DataFrame) -> dict[str, Any]:
    """Validate destination cleaning results before dispatch."""
    if "DestinationStatus" not in df.columns:
        raise ValueError("Destination cleaning has not been run. Missing DestinationStatus column.")
    unknown = df[df["DestinationStatus"] == "unknown"]
    manual = df[df["DestinationStatus"] == "needs_manual_validation"]
    return {
        "total_rows": int(len(df)),
        "valid_destinations": int((df["DestinationStatus"] == "valid").sum()),
        "needs_manual_validation": int(len(manual)),
        "unknown_destinations": int(len(unknown)),
        "unknown_list": sorted(str(value) for value in unknown.get("CleanAddress", pd.Series(dtype=str)).dropna().unique()),
    }


def save_unknown_destinations(df: pd.DataFrame, output_path: str | Path = UNKNOWN_DESTINATIONS_PATH) -> None:
    """Save unknown/needs-review destinations to CSV for manual inspection.
    
    Failures (disk full, permission denied, etc.) are logged but do not raise exceptions.
    This function is optional and should not block critical operations.
    """
    if df.empty or "DestinationStatus" not in df.columns:
        return
    
    needs_review = df[df["DestinationStatus"].isin(["unknown", "needs_manual_validation"])].copy()
    if needs_review.empty:
        return
    
    try:
        out = pd.DataFrame(
            {
                "OriginalAddress": needs_review.get("Adresse", needs_review.get("original_address", pd.Series(dtype=str))),
                "CleanedAddress": needs_review["CleanAddress"],
                "SuggestedDestination": needs_review["DetectedDestination"],
                "SuggestedZone": needs_review["DestinationZone"],
                "SimilarityScore": needs_review["DestinationScore"],
                "ManualDestination": "",
                "ManualZone": "",
            }
        ).drop_duplicates()
        
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(output, index=False, encoding="utf-8-sig")
    
    except (OSError, IOError, PermissionError) as e:
        # Disk full, permission denied, path too long, etc. — log and continue
        import sys
        print(f"Warning: Could not save unknown destinations to {output_path}: {str(e)}", file=sys.stderr)
    except Exception as e:
        # Catch any other CSV writing errors (e.g., invalid column types)
        import sys
        print(f"Warning: Error writing unknown destinations CSV: {str(e)}", file=sys.stderr)


def import_destination_corrections(corrections_file: str) -> None:
    """Import manual corrections and save them as aliases."""
    corrections = pd.read_csv(corrections_file)
    manual = _load_manual_aliases()
    official_lookup = {normalize_basic_text(payload["official_name"]): (key, payload) for key, payload in DESTINATION_ALIASES.items()}
    for _, row in corrections.iterrows():
        destination = str(row.get("ManualDestination", "")).strip()
        zone = str(row.get("ManualZone", "")).strip().upper()
        alias = str(row.get("CleanedAddress", "")).strip() or clean_destination_text(row.get("OriginalAddress", ""))
        if not destination or not zone or not alias:
            continue
        found = official_lookup.get(normalize_basic_text(destination))
        key = found[0] if found else re.sub(r"\W+", "_", destination.upper()).strip("_")
        payload = manual.setdefault(key, {"official_name": destination, "zone": zone, "aliases": []})
        payload["official_name"] = destination
        payload["zone"] = zone
        aliases = set(payload.get("aliases", []))
        aliases.add(alias)
        payload["aliases"] = sorted(aliases)
    ALIASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALIASES_PATH.write_text(json.dumps(manual, indent=2, ensure_ascii=False), encoding="utf-8")


def _best_fuzzy_match(text: str, choices: list[str]) -> tuple[str, float] | None:
    """Find best fuzzy match using hybrid approach: fast single-scorer first, multi-scorer fallback.
    
    Strategy:
    1. Try fast token_set_ratio first (handles most cases)
    2. If score < FALLBACK_THRESHOLD (90%), use multi-scorer for accuracy on ambiguous matches
    
    This keeps near-100% accuracy for clear cases while minimizing cost for borderline matches.
    """
    # Convert list to tuple for hashability, then delegate to cached function
    return _best_fuzzy_match_cached(text, tuple(choices))


@lru_cache(maxsize=2048)
def _best_fuzzy_match_cached(text: str, choices_tuple: tuple[str, ...]) -> tuple[str, float] | None:
    """Cached hybrid fuzzy match that operates on tuples.
    
    Threshold tuning:
    - If single-scorer (token_set_ratio) >= 70%, use it directly (fast path)
    - If single-scorer < 70%, try multi-scorer for accuracy on hard cases
    
    This balances speed (most matches are straightforward) with accuracy (hard cases get full treatment).
    """
    if not text or not choices_tuple:
        return None
    
    # Step 1: Try fast single-scorer (token_set_ratio) first
    fast_match = process.extractOne(text, choices_tuple, scorer=fuzz.token_set_ratio)
    
    if fast_match and fast_match[1] >= 85:  # Accept fast result for matches above confidence threshold
        return (str(fast_match[0]), round(float(fast_match[1]), 2))
    
    # Step 2: Only for difficult/low-confidence matches, try full multi-scorer
    scorers = [
        fuzz.token_sort_ratio,
        fuzz.token_set_ratio,
        fuzz.partial_ratio,
        fuzz.WRatio,
    ]
    
    best_alias = None
    best_score = 0
    
    for scorer in scorers:
        match = process.extractOne(text, choices_tuple, scorer=scorer)
        if match and match[1] > best_score:
            best_alias = match[0]
            best_score = match[1]
    
    return (str(best_alias), round(float(best_score), 2)) if best_alias else None


def _valid_result(original: str, cleaned: str, payload: dict[str, Any], alias: str, score: float, method: str) -> dict[str, Any]:
    return _result(original, cleaned, payload["official_name"], payload["zone"], alias, score, "valid", method)


def _manual_result(original: str, cleaned: str, payload: dict[str, Any], alias: str, score: float, method: str) -> dict[str, Any]:
    return _result(original, cleaned, payload["official_name"], payload["zone"], alias, score, "needs_manual_validation", method)


def _unknown_result(original: str, cleaned: str) -> dict[str, Any]:
    return _result(original, cleaned, UNKNOWN_ZONE, UNKNOWN_ZONE, None, 0, "unknown", "unknown")


def _result(
    original: str,
    cleaned: str,
    destination: str,
    zone: str,
    alias: str | None,
    score: float,
    status: str,
    method: str,
) -> dict[str, Any]:
    return {
        "original_address": original,
        "cleaned_address": cleaned,
        "detected_destination": destination,
        "zone": zone,
        "matched_alias": alias,
        "similarity_score": round(float(score), 2),
        "validation_status": status,
        "method": method,
    }


def _alias_index() -> dict[str, dict[str, Any]]:
    aliases: dict[str, dict[str, Any]] = {}
    for _key, payload in _merged_aliases().items():
        for alias in payload.get("aliases", []):
            for candidate in _alias_forms(alias):
                aliases[candidate] = payload
    return dict(sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True))


def _alias_forms(alias: str) -> set[str]:
    normalized = normalize_basic_text(alias)
    cleaned = clean_destination_text_without_repair(alias)
    return {value for value in [normalized, cleaned, normalized.replace(" ", ""), cleaned.replace(" ", "")] if value}


def clean_destination_text_without_repair(text: str) -> str:
    normalized = normalize_basic_text(text)
    tokens = [token for token in normalized.split() if token not in _normalized_generic_words()]
    return re.sub(r"\s+", " ", " ".join(tokens)).strip()


def _known_alias_texts() -> list[str]:
    values: list[str] = []
    for payload in _merged_aliases().values():
        values.extend(str(alias) for alias in payload.get("aliases", []))
    return values


def _normalized_generic_words() -> set[str]:
    return {normalize_basic_text(word) for word in GENERIC_WORDS}


def _load_manual_aliases() -> dict[str, dict[str, Any]]:
    if not ALIASES_PATH.exists():
        ALIASES_PATH.parent.mkdir(parents=True, exist_ok=True)
        ALIASES_PATH.write_text("{}", encoding="utf-8")
        return {}
    try:
        return json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _merged_aliases() -> dict[str, dict[str, Any]]:
    merged = json.loads(json.dumps(DESTINATION_ALIASES, ensure_ascii=False))
    for key, value in _load_manual_aliases().items():
        if key in merged:
            aliases = set(merged[key].get("aliases", []))
            aliases.update(value.get("aliases", []))
            merged[key]["aliases"] = sorted(aliases)
        else:
            merged[key] = value
    return merged
