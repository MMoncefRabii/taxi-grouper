"""
Compare single-scorer (current) vs multi-scorer (original) fuzzy matching accuracy.
Tests token_set_ratio alone vs a combination of all 4 rapidfuzz scorers.
"""
from pathlib import Path
import pandas as pd
from rapidfuzz import fuzz, process
from src.core.preprocessing import load_dispatch_excel, detect_columns, filter_dataframe
from src.core.destination_cleaner import (
    clean_destination_text,
    normalize_basic_text,
    _alias_index,
    _valid_result,
    _manual_result,
    _unknown_result,
    _result
)
from src.config import UNKNOWN_ZONE
from typing import Any


def _best_fuzzy_match_single(text: str, choices: list[str]) -> tuple[str, float] | None:
    """Current implementation: single token_set_ratio scorer (fastest)."""
    if not text or not choices:
        return None
    match = process.extractOne(text, choices, scorer=fuzz.token_set_ratio)
    return (str(match[0]), round(float(match[1]), 2)) if match else None


def _best_fuzzy_match_multi(text: str, choices: list[str]) -> tuple[str, float] | None:
    """Original approach: try 4 different scorers and take the best result."""
    if not text or not choices:
        return None
    
    scorers = [
        fuzz.token_sort_ratio,
        fuzz.token_set_ratio,
        fuzz.partial_ratio,
        fuzz.WRatio,
    ]
    
    best_alias = None
    best_score = 0
    
    for scorer in scorers:
        match = process.extractOne(text, choices, scorer=scorer)
        if match and match[1] > best_score:
            best_alias = match[0]
            best_score = match[1]
    
    return (str(best_alias), round(float(best_score), 2)) if best_alias else None


def detect_clean_destination_single(raw_address: str, aliases: dict) -> dict[str, Any]:
    """Current single-scorer version."""
    original = "" if raw_address is None else str(raw_address)
    cleaned = clean_destination_text(original)
    normalized = normalize_basic_text(original)
    search_texts = [text for text in [normalized, normalized.replace(" ", ""), cleaned, cleaned.replace(" ", "")] if text]
    if not search_texts:
        return _unknown_result(original, cleaned)

    lookup = {alias: payload for alias, payload in aliases.items()}
    for text in search_texts:
        if text in lookup:
            return _valid_result(original, cleaned, lookup[text], text, 100, "exact")

    for alias, payload in aliases.items():
        import re
        if any(alias and re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text) for text in search_texts):
            return _valid_result(original, cleaned, payload, alias, 100, "substring")

    choices = list(aliases.keys())
    best = _best_fuzzy_match_single(cleaned or normalized, choices)
    if best:
        alias, score = best
        payload = lookup[alias]
        if score >= 85:
            return _valid_result(original, cleaned, payload, alias, score, "fuzzy")
        if score >= 70:
            return _manual_result(original, cleaned, payload, alias, score, "fuzzy")
    
    return _unknown_result(original, cleaned)


def detect_clean_destination_multi(raw_address: str, aliases: dict) -> dict[str, Any]:
    """Multi-scorer version (original approach)."""
    original = "" if raw_address is None else str(raw_address)
    cleaned = clean_destination_text(original)
    normalized = normalize_basic_text(original)
    search_texts = [text for text in [normalized, normalized.replace(" ", ""), cleaned, cleaned.replace(" ", "")] if text]
    if not search_texts:
        return _unknown_result(original, cleaned)

    lookup = {alias: payload for alias, payload in aliases.items()}
    for text in search_texts:
        if text in lookup:
            return _valid_result(original, cleaned, lookup[text], text, 100, "exact")

    for alias, payload in aliases.items():
        import re
        if any(alias and re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text) for text in search_texts):
            return _valid_result(original, cleaned, payload, alias, 100, "substring")

    choices = list(aliases.keys())
    best = _best_fuzzy_match_multi(cleaned or normalized, choices)
    if best:
        alias, score = best
        payload = lookup[alias]
        if score >= 85:
            return _valid_result(original, cleaned, payload, alias, score, "fuzzy")
        if score >= 70:
            return _manual_result(original, cleaned, payload, alias, score, "fuzzy")
    
    return _unknown_result(original, cleaned)


def compare_implementations(file_path: str):
    df = load_dispatch_excel(file_path)
    cols = detect_columns(df)
    df_filtered = filter_dataframe(df, cols, time_value=None, type_course=None, operation=None)
    
    print(f"Testing on {len(df_filtered)} rows\n")
    
    aliases = _alias_index()
    
    # Run single-scorer version
    results_single = []
    for _, row in df_filtered.iterrows():
        result = detect_clean_destination_single(row[cols.address], aliases)
        results_single.append(result["validation_status"])
    
    # Run multi-scorer version
    results_multi = []
    for _, row in df_filtered.iterrows():
        result = detect_clean_destination_multi(row[cols.address], aliases)
        results_multi.append(result["validation_status"])
    
    # Summarize single-scorer
    df_single = pd.Series(results_single).value_counts()
    print("=== CURRENT (single token_set_ratio) ===")
    valid = int(df_single.get("valid", 0))
    manual = int(df_single.get("needs_manual_validation", 0))
    unknown = int(df_single.get("unknown", 0))
    print(f"Valid (>=85): {valid}")
    print(f"Manual (70-84): {manual}")
    print(f"Unknown: {unknown}")
    print(f"Total detected: {valid + manual} ({100 * (valid + manual) / len(df_filtered):.1f}%)\n")
    
    # Summarize multi-scorer
    df_multi = pd.Series(results_multi).value_counts()
    print("=== ORIGINAL (multi-scorer: token_sort + token_set + partial + WRatio) ===")
    valid_multi = int(df_multi.get("valid", 0))
    manual_multi = int(df_multi.get("needs_manual_validation", 0))
    unknown_multi = int(df_multi.get("unknown", 0))
    print(f"Valid (>=85): {valid_multi}")
    print(f"Manual (70-84): {manual_multi}")
    print(f"Unknown: {unknown_multi}")
    print(f"Total detected: {valid_multi + manual_multi} ({100 * (valid_multi + manual_multi) / len(df_filtered):.1f}%)\n")
    
    # Comparison
    print("=== COMPARISON ===")
    print(f"Unknown increase (single vs multi): {unknown - unknown_multi} (+{100 * (unknown - unknown_multi) / len(df_filtered):.1f}%)")
    print(f"Manual increase (single vs multi): {manual - manual_multi} ({manual - manual_multi:+d})")
    print(f"Valid decrease (single vs multi): {valid - valid_multi} ({valid - valid_multi:+d})")
    
    if unknown > unknown_multi:
        print(f"\n⚠️  REGRESSION: Single-scorer has {unknown - unknown_multi} MORE unknown destinations than multi-scorer")
    elif unknown < unknown_multi:
        print(f"\n✓ IMPROVEMENT: Single-scorer has {unknown_multi - unknown} FEWER unknown destinations than multi-scorer")
    else:
        print(f"\n✓ NO CHANGE in unknown count")


if __name__ == "__main__":
    compare_implementations("test_ramassage.xlsx")
