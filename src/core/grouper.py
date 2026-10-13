"""Strict rule-based and ML-scored taxi grouping."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from itertools import combinations
import math
from numbers import Real
import re
from typing import Any

import pandas as pd

from ..config import GrouperConfig, MAX_TAXI_CAPACITY, TAXI_COLUMN, UNKNOWN_ZONE
from .destination_cleaner import add_clean_destination_columns, validate_cleaned_destinations
from .ml_model import load_model, score_pair, score_pairs
from .preprocessing import ColumnMap, detect_columns
from .zones import ZONE_NAMES, zones_are_compatible

DEBUG_COLUMNS = [
    "CleanAddress",
    "DetectedDestination",
    "DestinationZone",
    "DestinationScore",
    "DestinationStatus",
    "Zone",
    "MatchedAlias",
    "DestinationConfidence",
    "DetectionMethod",
    "NeedsManualValidation",
    "NeedsManualReview",
    "GroupReason",
    "RuleUsed",
    "ValidationStatus",
    "ValidationMessage",
    "SourceSheet",
    "BlockID",
]
MAIN_AGENT_COLUMNS = ["Date", "Matricule", "Nom - Prénom", "Nom - Prenom", "Opération", "Operation", "Site", "Adresse", "Heure d'arrivée", "Heure d'arrivee"]

DESTINATION_COMPATIBILITY: dict[str, set[str]] = {
    "Ibn Khaldoun": {"Ibn Khaldoun", "Cite Errafeha", "Omrane", "Mnihla", "Tahrir", "Ettadhamen"},
    "Cite Errafeha": {"Cite Errafeha", "Ibn Khaldoun", "Omrane", "Mnihla", "Tahrir", "Ettadhamen"},
    "Sidi Hssine": {"Sidi Hssine", "Zahrouni"},
    "Zahrouni": {"Zahrouni", "Sidi Hssine"},
    "Jaafer": {"Jaafer", "Ghazela", "Ariana Soghra", "Ariana", "Cité La Gazelle"},
    "Ghazela": {"Ghazela", "Jaafer", "Ariana Soghra", "Ariana", "Cité La Gazelle"},
    "Ariana Soghra": {"Ariana Soghra", "Jaafer", "Ghazela", "Ariana", "Cité La Gazelle"},
    "Ariana": {"Ariana", "Ghazela", "Jaafer", "Ariana Soghra", "Cité La Gazelle"},
    "Cité La Gazelle": {"Cité La Gazelle", "Ariana", "Ghazela", "Jaafer", "Ariana Soghra"},
}


def enrich_zones(df: pd.DataFrame, address_col: str) -> pd.DataFrame:
    """Detect destination and zone for each row before any grouping happens."""
    result = add_clean_destination_columns(df, address_col, save_unknown=False)
    result["Zone Name"] = result["DestinationZone"].apply(lambda zone: ZONE_NAMES.get(str(zone), UNKNOWN_ZONE))
    result["GroupReason"] = ""
    result["RuleUsed"] = ""
    result["ValidationStatus"] = ""
    result["ValidationMessage"] = ""
    if "SourceSheet" not in result.columns:
        result["SourceSheet"] = ""
    if "BlockID" not in result.columns:
        result["BlockID"] = ""
    if "UnassignedReason" not in result.columns:
        result["UnassignedReason"] = ""
    return result


def group_agents(
    df: pd.DataFrame,
    columns: ColumnMap | None = None,
    config: GrouperConfig | None = None,
    use_ml: bool = True,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Group agents into taxis using hard rules first.

    ML is deliberately limited to sorting candidates that already pass hard
    compatibility rules. It never creates final groups directly.
    """
    config = config or GrouperConfig()
    columns = columns or detect_columns(df)
    capacity = config.max_capacity
    if capacity > MAX_TAXI_CAPACITY:
        raise ValueError("Taxi capacity cannot exceed the business limit of 4.")

    clean_input = _drop_empty_agent_rows(df)
    columns = detect_columns(clean_input)
    result = enrich_zones(clean_input, columns.address)
    result["_original_order"] = range(len(result))
    result["UnassignedReason"] = ""
    if "Taxi" in result.columns:
        result["_InputTaxi"] = result["Taxi"]
        result["Taxi"] = ""
    result[config.taxi_column] = pd.NA  # Initialize as NA (numeric-compatible) instead of empty string
    date_col = _find_existing_col(result, ["Date"])
    if date_col is None:
        date_values = pd.Series(pd.NaT, index=result.index, dtype="datetime64[ns]")
    else:
        date_values = _parse_dispatch_dates(result[date_col], day_first=config.day_first)
    result["_DispatchDateKey"] = date_values.dt.strftime("%Y-%m-%d")
    dispatch_id_col = _find_source_dispatch_id_column(result)
    if dispatch_id_col is None:
        dispatch_ids = pd.Series(None, index=result.index, dtype=object)
    else:
        dispatch_ids = result[dispatch_id_col].map(_clean_source_dispatch_id)
    result["_SourceDispatchIDKey"] = dispatch_ids
    invalid_dates = result["_DispatchDateKey"].isna()
    invalid_dispatch_ids = result["_SourceDispatchIDKey"].isna()
    result.loc[invalid_dates, "GroupReason"] = "MISSING_DATE"
    result.loc[invalid_dates, "UnassignedReason"] = "MISSING_DATE"
    result.loc[~invalid_dates & invalid_dispatch_ids, "GroupReason"] = "MISSING_DISPATCH_ID"
    result.loc[~invalid_dates & invalid_dispatch_ids, "UnassignedReason"] = "MISSING_DISPATCH_ID"
    warnings: list[str] = []

    model = load_model(config.model_path) if use_ml else None
    if use_ml and model is None:
        warnings.append("No trained model found. Using rule-based grouping only.")
    clean_validation = validate_cleaned_destinations(result)
    if clean_validation["unknown_destinations"]:
        warnings.append(f"{clean_validation['unknown_destinations']} unknown destinations need manual validation.")
    if clean_validation["needs_manual_validation"]:
        warnings.append(f"{clean_validation['needs_manual_validation']} low-confidence destinations need manual validation.")

    all_groups: list[dict[str, Any]] = []
    assigned: set[int] = set(result.index[invalid_dates | invalid_dispatch_ids])

    groupable = result.loc[~(invalid_dates | invalid_dispatch_ids)]
    for _block_key, block_indices in _iter_dispatch_blocks(groupable, columns):
        groups = _group_block(result, block_indices, columns, model, capacity)
        _apply_dispatch_preferences(result, groups, capacity)
        for group in groups:
            indices = list(group["indices"])
            overlap = assigned.intersection(indices)
            if overlap:
                raise RuntimeError(f"Internal grouping error: duplicated rows {sorted(overlap)}")
            assigned.update(indices)
            all_groups.append(group)

    missing = [idx for idx in result.index if idx not in assigned]
    for idx in missing:
        all_groups.append({"indices": [idx], "reason": "Fallback single agent", "rule": "fallback"})
        assigned.add(idx)

    for taxi_number, group in enumerate(all_groups, start=1):
        indices = list(group["indices"])
        if len(indices) > capacity:
            raise RuntimeError("Internal grouping error: taxi capacity exceeded.")
        if not _group_zones_valid(result, indices):
            raise RuntimeError(f"Internal grouping error: incompatible zones in taxi {taxi_number}.")
        result.loc[indices, config.taxi_column] = taxi_number
        result.loc[indices, "GroupReason"] = str(group["reason"])
        result.loc[indices, "RuleUsed"] = str(group["rule"])

    result = result.drop(columns=["_DispatchDateKey", "_SourceDispatchIDKey"])
    result = result.sort_values([config.taxi_column, "_original_order"], kind="stable").drop(columns=["_original_order"]).reset_index(drop=True)
    validation = validate_dispatch(
        result,
        taxi_column=config.taxi_column,
        capacity=capacity,
        day_first=config.day_first,
    )
    if validation["errors"]:
        warnings.extend(validation["errors"])
    return result, warnings


def _apply_dispatch_preferences(df: pd.DataFrame, groups: list[dict[str, Any]], capacity: int) -> None:
    _prefer_destination_with_three_of_another(
        df,
        groups,
        preferred_destination="Ghazela",
        anchor_destination="Ariana",
    )
    _move_one_destination_to_fill(
        df,
        groups,
        source_destination="Oued Lil",
        target_destination="Mornaguia",
        capacity=capacity,
    )


def _prefer_destination_with_three_of_another(
    df: pd.DataFrame,
    groups: list[dict[str, Any]],
    preferred_destination: str,
    anchor_destination: str,
) -> None:
    preferred_group = _find_group(groups, df, preferred_destination)
    if preferred_group is None:
        return
    preferred_idx = next((idx for idx in preferred_group["indices"] if str(df.at[idx, "DetectedDestination"]) == preferred_destination), None)
    if preferred_idx is None:
        return
    for anchor_group in groups:
        if anchor_group is preferred_group:
            continue
        anchor_indices = list(anchor_group.get("indices", []))
        anchor_count = sum(1 for idx in anchor_indices if str(df.at[idx, "DetectedDestination"]) == anchor_destination)
        if anchor_count != 3:
            continue
        swap_idx = next((idx for idx in anchor_indices if str(df.at[idx, "DetectedDestination"]) != anchor_destination), None)
        if swap_idx is None:
            continue
        new_anchor = [idx for idx in anchor_indices if idx != swap_idx]
        new_preferred = [idx for idx in preferred_group["indices"] if idx != preferred_idx]
        if not _can_add_to_group(df, new_anchor, preferred_idx):
            continue
        if new_preferred and not _can_add_to_group(df, new_preferred, swap_idx):
            continue
        anchor_group["indices"] = new_anchor + [preferred_idx]
        preferred_group["indices"] = new_preferred + [swap_idx]
        anchor_group["reason"] = "Same destination + same zone fill"
        anchor_group["rule"] = "same_zone_fill"
        preferred_group["reason"] = _partial_group_reason(df, preferred_group["indices"])
        preferred_group["rule"] = _partial_group_rule(df, preferred_group["indices"])
        return


def _move_one_destination_to_fill(
    df: pd.DataFrame,
    groups: list[dict[str, Any]],
    source_destination: str,
    target_destination: str,
    capacity: int,
) -> None:
    target_group = _find_group(groups, df, target_destination, max_size=capacity - 1)
    source_group = _find_group(groups, df, source_destination, min_size=capacity)
    if target_group is None or source_group is None:
        return
    candidate = next((idx for idx in source_group["indices"] if str(df.at[idx, "DetectedDestination"]) == source_destination), None)
    if candidate is None or not _can_add_to_group(df, list(target_group["indices"]), candidate):
        return
    source_group["indices"] = [idx for idx in source_group["indices"] if idx != candidate]
    target_group["indices"].append(candidate)
    target_group["reason"] = "Compatible zone fill"
    target_group["rule"] = "compatible_zone_fill"
    source_group["reason"] = _partial_group_reason(df, source_group["indices"])
    source_group["rule"] = _partial_group_rule(df, source_group["indices"])


def _find_group(
    groups: list[dict[str, Any]],
    df: pd.DataFrame,
    destination: str,
    min_size: int = 1,
    max_size: int | None = None,
) -> dict[str, Any] | None:
    for group in groups:
        indices = list(group.get("indices", []))
        if len(indices) < min_size:
            continue
        if max_size is not None and len(indices) > max_size:
            continue
        if any(str(df.at[idx, "DetectedDestination"]) == destination for idx in indices):
            return group
    return None


def _iter_dispatch_blocks(df: pd.DataFrame, columns: ColumnMap) -> list[tuple[tuple[Any, ...], list[int]]]:
    block_cols = _block_columns(df, columns)
    if not block_cols:
        return [(("ALL",), df.index.tolist())]
    blocks: list[tuple[tuple[Any, ...], list[int]]] = []
    grouped = df.groupby(block_cols, sort=False, dropna=False)
    for key, block in grouped:
        if not isinstance(key, tuple):
            key = (key,)
        blocks.append((key, block.index.tolist()))
    return blocks


def _block_columns(df: pd.DataFrame, columns: ColumnMap) -> list[str]:
    candidates = [
        "_DispatchDateKey",
        "_SourceDispatchIDKey",
        columns.time,
        columns.type_course,
        "Dispatch Type",
        "Type de course",
        "Ramassage / Retour",
        "Call Center Location",
        "CallCenter",
    ]
    seen: set[str] = set()
    block_cols: list[str] = []
    for col in candidates:
        if col and col in df.columns and col not in seen:
            seen.add(col)
            block_cols.append(col)
    return block_cols


def _find_source_dispatch_id_column(df: pd.DataFrame) -> str | None:
    aliases = {
        "dispatchid",
        "sourcedispatchid",
        "iddispatch",
        "dispatchnumber",
        "dispatchno",
    }
    for column in df.columns:
        normalized = "".join(character.lower() for character in str(column) if character.isalnum())
        if normalized in aliases:
            return column
    return None


def _parse_dispatch_dates(values: pd.Series, day_first: bool = True) -> pd.Series:
    parsed: list[pd.Timestamp | pd.NaT] = []
    for value in values:
        if pd.isna(value):
            parsed.append(pd.NaT)
        elif isinstance(value, (datetime, date, pd.Timestamp)):
            parsed.append(pd.Timestamp(value))
        elif isinstance(value, Real) and not isinstance(value, bool):
            serial = float(value)
            parsed.append(
                pd.to_datetime(serial, unit="D", origin="1899-12-30", errors="coerce")
                if math.isfinite(serial)
                else pd.NaT
            )
        elif isinstance(value, str):
            text = value.strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                date_format = "%Y-%m-%d"
            elif re.fullmatch(r"\d{2}/\d{2}/\d{4}", text):
                date_format = "%d/%m/%Y" if day_first else "%m/%d/%Y"
            elif re.fullmatch(r"\d{2}-\d{2}-\d{4}", text):
                date_format = "%d-%m-%Y" if day_first else "%m-%d-%Y"
            else:
                parsed.append(pd.NaT)
                continue
            parsed.append(pd.to_datetime(text, format=date_format, errors="coerce"))
        else:
            parsed.append(pd.NaT)
    return pd.Series(pd.to_datetime(parsed), index=values.index)


def _clean_source_dispatch_id(value: object) -> str | None:
    if pd.isna(value):
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _drop_empty_agent_rows(df: pd.DataFrame) -> pd.DataFrame:
    main_cols = [col for col in MAIN_AGENT_COLUMNS if col in df.columns]
    if not main_cols:
        return df.copy().reset_index(drop=True)
    keep = ~df[main_cols].apply(lambda row: all(pd.isna(value) or str(value).strip() == "" for value in row), axis=1)
    return df.loc[keep].copy().reset_index(drop=True)


def _group_block(
    df: pd.DataFrame,
    block_indices: list[int],
    columns: ColumnMap,
    model: object | None,
    capacity: int,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    assigned: set[int] = set()

    known = [idx for idx in block_indices if _is_known_groupable(df, idx)]
    review = [idx for idx in block_indices if idx not in known]

    partials = _create_destination_groups(df, known, columns, model, capacity, groups, assigned)
    _fill_partials(df, partials, columns, model, capacity, same_zone_only=True)
    _fill_partials(df, partials, columns, model, capacity, same_zone_only=False)
    for partial in partials:
        if partial["indices"]:
            groups.append(
                {
                    "indices": list(partial["indices"]),
                    "reason": _partial_group_reason(df, partial["indices"]),
                    "rule": _partial_group_rule(df, partial["indices"]),
                }
            )
            assigned.update(partial["indices"])

    review_buckets: dict[str, list[int]] = defaultdict(list)
    for idx in review:
        review_buckets[str(df.at[idx, "CleanAddress"])].append(idx)
    for indices in review_buckets.values():
        indices = sorted(indices, key=lambda idx: int(df.at[idx, "_original_order"]))
        for chunk in _chunks(indices, capacity):
            groups.append(
                {
                    "indices": chunk,
                    "reason": "Manual review required" if _any_manual_review(df, chunk) else "Unknown address",
                    "rule": "manual_review",
                }
            )
            assigned.update(chunk)

    for idx in block_indices:
        if idx not in assigned:
            groups.append({"indices": [idx], "reason": "Single remaining agent", "rule": "single_remaining"})
            assigned.add(idx)

    return groups


def group_agents_by_destination_then_zone(
    df: pd.DataFrame,
    columns: ColumnMap | None = None,
    config: GrouperConfig | None = None,
    use_ml: bool = True,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Group agents into taxis using:
    1. Same destination first
    2. Same zone to complete incomplete taxis
    3. Compatible zones only after same-zone options
    4. Unknown addresses separately
    """
    return group_agents(df, columns=columns, config=config, use_ml=use_ml)


def _create_destination_groups(
    df: pd.DataFrame,
    indices: list[int],
    columns: ColumnMap,
    model: object | None,
    capacity: int,
    groups: list[dict[str, Any]],
    assigned: set[int],
) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[int]] = defaultdict(list)
    for idx in indices:
        buckets[(str(df.at[idx, "DestinationZone"]), str(df.at[idx, "DetectedDestination"]))].append(idx)

    partials: list[dict[str, Any]] = []
    for (zone, destination), bucket in sorted(buckets.items(), key=lambda item: (item[0][0], item[0][1])):
        ordered = _ml_sort(bucket, df, columns, model)
        while len(ordered) >= capacity:
            chunk = ordered[:capacity]
            groups.append({"indices": chunk, "reason": "Same destination", "rule": "same_destination"})
            assigned.update(chunk)
            ordered = ordered[capacity:]
        if ordered:
            partials.append({"indices": ordered, "zone": zone, "destination": destination})
    return partials


def _fill_partials(
    df: pd.DataFrame,
    partials: list[dict[str, Any]],
    columns: ColumnMap,
    model: object | None,
    capacity: int,
    same_zone_only: bool,
) -> None:
    for partial in partials:
        while 0 < len(partial["indices"]) < capacity:
            donor = _best_donor_partial(df, partials, partial, columns, model, same_zone_only)
            if donor is None:
                break
            room = capacity - len(partial["indices"])
            movable = _best_movable_indices(df, donor["indices"], partial["indices"], columns, model, room)
            if not movable:
                break
            partial["indices"].extend(movable)
            donor["indices"] = [idx for idx in donor["indices"] if idx not in set(movable)]


def _best_donor_partial(
    df: pd.DataFrame,
    partials: list[dict[str, Any]],
    target: dict[str, Any],
    columns: ColumnMap,
    model: object | None,
    same_zone_only: bool,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    room = MAX_TAXI_CAPACITY - len(target["indices"])
    for donor in partials:
        if donor is target or not donor["indices"]:
            continue
        if len(donor["indices"]) > room:
            continue
        if same_zone_only and str(donor["zone"]) != str(target["zone"]):
            continue
        if not same_zone_only and str(donor["zone"]) == str(target["zone"]):
            continue
        if any(_can_add_to_group(df, target["indices"], idx) for idx in donor["indices"]):
            candidates.append(donor)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda donor: (
            0 if str(donor["destination"]) == str(target["destination"]) else 1,
            str(donor["zone"]),
            str(donor["destination"]),
            min(int(df.at[idx, "_original_order"]) for idx in donor["indices"]),
        ),
    )[0]


def _best_movable_indices(
    df: pd.DataFrame,
    donor_indices: list[int],
    target_indices: list[int],
    columns: ColumnMap,
    model: object | None,
    room: int,
) -> list[int]:
    if len(donor_indices) > room:
        return []
    movable: list[int] = []
    current = list(target_indices)
    for idx in _ml_sort(list(donor_indices), df, columns, model, anchor_indices=target_indices):
        if len(movable) >= room:
            break
        if _can_add_to_group(df, current, idx):
            movable.append(idx)
            current.append(idx)
    return movable


def _partial_group_reason(df: pd.DataFrame, indices: list[int]) -> str:
    destinations = {str(df.at[idx, "DetectedDestination"]) for idx in indices}
    zones = {str(df.at[idx, "DestinationZone"]) for idx in indices}
    if len(destinations) == 1:
        return "Same destination"
    if len(zones) == 1:
        return "Same destination + same zone fill"
    return "Compatible zone fill"


def _partial_group_rule(df: pd.DataFrame, indices: list[int]) -> str:
    destinations = {str(df.at[idx, "DetectedDestination"]) for idx in indices}
    zones = {str(df.at[idx, "DestinationZone"]) for idx in indices}
    if len(destinations) == 1:
        return "same_destination"
    if len(zones) == 1:
        return "same_zone_fill"
    return "compatible_zone_fill"


def _make_full_groups(
    df: pd.DataFrame,
    indices: list[int],
    assigned: set[int],
    key_col: str,
    reason: str,
    rule: str,
    capacity: int,
    groups: list[dict[str, Any]],
    columns: ColumnMap,
    model: object | None,
    keep_partial_groups: bool = False,
) -> list[int]:
    buckets: dict[str, list[int]] = defaultdict(list)
    for idx in indices:
        if idx not in assigned:
            buckets[str(df.at[idx, key_col])].append(idx)

    leftovers: list[int] = []
    for _key, bucket in sorted(buckets.items(), key=lambda item: item[0]):
        ordered = _ml_sort(bucket, df, columns, model)
        while len(ordered) >= capacity:
            chunk = ordered[:capacity]
            groups.append({"indices": chunk, "reason": reason, "rule": rule})
            assigned.update(chunk)
            ordered = ordered[capacity:]
        if keep_partial_groups and len(ordered) > 1:
            groups.append({"indices": ordered, "reason": reason, "rule": rule})
            assigned.update(ordered)
            ordered = []
        leftovers.extend(ordered)
    return leftovers


def _merge_compatible_partials(
    df: pd.DataFrame,
    partials: list[list[int]],
    columns: ColumnMap,
    model: object | None,
    capacity: int,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    unassigned = {idx for partial in partials for idx in partial}
    ordered_seeds = sorted(unassigned, key=lambda idx: (str(df.at[idx, "Zone"]), int(df.at[idx, "_original_order"])))

    for seed in ordered_seeds:
        if seed not in unassigned:
            continue
        taxi = [seed]
        unassigned.remove(seed)
        while len(taxi) < capacity:
            candidates = [idx for idx in unassigned if _can_add_to_group(df, taxi, idx)]
            if not candidates:
                break
            best = _ml_sort(candidates, df, columns, model, anchor_indices=taxi)[0]
            taxi.append(best)
            unassigned.remove(best)
        zones = sorted({str(df.at[idx, "DestinationZone"]) for idx in taxi})
        if len(zones) == 1:
            reason = "Same zone"
            rule = "same_zone_partial"
        else:
            reason = f"Compatible zones {'-'.join(zones)}"
            rule = "compatible_zones"
        groups.append({"indices": taxi, "reason": reason, "rule": rule})

    return groups


def _is_known_groupable(df: pd.DataFrame, idx: int) -> bool:
    return (
        str(df.at[idx, "DestinationZone"]) != UNKNOWN_ZONE
        and str(df.at[idx, "DetectedDestination"]) != UNKNOWN_ZONE
        and str(df.at[idx, "DestinationStatus"]) == "valid"
        and not bool(df.at[idx, "NeedsManualValidation"])
    )


def _any_manual_review(df: pd.DataFrame, indices: list[int]) -> bool:
    return any(bool(df.at[idx, "NeedsManualReview"]) for idx in indices)


def _can_add_to_group(df: pd.DataFrame, group_indices: list[int], candidate: int) -> bool:
    if len(group_indices) >= MAX_TAXI_CAPACITY:
        return False
    if not _is_known_groupable(df, candidate):
        return False
    candidate_zone = str(df.at[candidate, "DestinationZone"])
    candidate_destination = str(df.at[candidate, "DetectedDestination"])
    return all(
        zones_are_compatible(str(df.at[idx, "DestinationZone"]), candidate_zone)
        and _destinations_are_compatible(str(df.at[idx, "DetectedDestination"]), candidate_destination)
        for idx in group_indices
    )


def _group_zones_valid(df: pd.DataFrame, indices: list[int]) -> bool:
    zones = [str(df.at[idx, "DestinationZone"]) for idx in indices]
    if UNKNOWN_ZONE in zones:
        return len(set(zones)) == 1
    zone_ok = all(zones_are_compatible(a, b) for a, b in combinations(zones, 2))
    destinations = [str(df.at[idx, "DetectedDestination"]) for idx in indices]
    destination_ok = all(_destinations_are_compatible(a, b) for a, b in combinations(destinations, 2))
    return zone_ok and destination_ok


def _destinations_are_compatible(destination_a: str, destination_b: str) -> bool:
    if destination_a == destination_b:
        return True
    allowed_a = DESTINATION_COMPATIBILITY.get(destination_a)
    allowed_b = DESTINATION_COMPATIBILITY.get(destination_b)
    if allowed_a is not None and destination_b not in allowed_a:
        return False
    if allowed_b is not None and destination_a not in allowed_b:
        return False
    return True


def _ml_sort(indices: list[int], df: pd.DataFrame, columns: ColumnMap, model: object | None, anchor_indices: list[int] | None = None) -> list[int]:
    if model is None or len(indices) <= 1:
        return sorted(
            indices,
            key=lambda idx: (
                str(df.at[idx, "DestinationZone"]),
                str(df.at[idx, "DetectedDestination"]),
                str(df.at[idx, "CleanAddress"]),
                int(df.at[idx, "_original_order"]),
            ),
        )
    
    # Skip ML if group is homogeneous (all same zone/destination) — ML won't change outcome
    zones = {str(df.at[idx, "DestinationZone"]) for idx in indices}
    destinations = {str(df.at[idx, "DetectedDestination"]) for idx in indices}
    if len(zones) == 1 and len(destinations) == 1:
        return sorted(indices, key=lambda idx: int(df.at[idx, "_original_order"]))
    
    anchors = anchor_indices or indices

    pair_indices: list[int] = []
    rows_a: list[pd.Series] = []
    rows_b: list[pd.Series] = []
    for idx in indices:
        for anchor in anchors:
            if anchor == idx or not _pair_passes_hard_rules(df, idx, anchor):
                continue
            pair_indices.append(idx)
            rows_a.append(df.loc[idx])
            rows_b.append(df.loc[anchor])

    if not pair_indices:
        return sorted(
            indices,
            key=lambda idx: (
                str(df.at[idx, "DestinationZone"]),
                str(df.at[idx, "DetectedDestination"]),
                str(df.at[idx, "CleanAddress"]),
                int(df.at[idx, "_original_order"]),
            ),
        )

    scores = score_pairs(model, rows_a, rows_b, columns)
    avg_scores: dict[int, list[float]] = {}
    for idx, score in zip(pair_indices, scores):
        avg_scores.setdefault(idx, []).append(score)

    def key(idx: int) -> tuple[float, str, int]:
        candidate_scores = avg_scores.get(idx, [])
        avg_score = sum(candidate_scores) / len(candidate_scores) if candidate_scores else 0.0
        return (-avg_score, str(df.at[idx, "CleanAddress"]), int(df.at[idx, "_original_order"]))

    return sorted(indices, key=key)


def _pair_passes_hard_rules(df: pd.DataFrame, idx_a: int, idx_b: int) -> bool:
    if not _is_known_groupable(df, idx_a) or not _is_known_groupable(df, idx_b):
        return False
    return zones_are_compatible(str(df.at[idx_a, "DestinationZone"]), str(df.at[idx_b, "DestinationZone"])) and _destinations_are_compatible(
        str(df.at[idx_a, "DetectedDestination"]),
        str(df.at[idx_b, "DetectedDestination"]),
    )


def _chunks(values: list[int], size: int) -> list[list[int]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def validate_dispatch(
    df: pd.DataFrame,
    taxi_column: str = TAXI_COLUMN,
    capacity: int = MAX_TAXI_CAPACITY,
    day_first: bool = True,
) -> dict[str, Any]:
    """
    Validate final taxi groups before export.

    Returns a dictionary with errors, warnings, and one report row per taxi.
    """
    result = df.copy()
    errors: list[str] = []
    warnings: list[str] = []
    taxi_reports: list[dict[str, Any]] = []

    if taxi_column not in result.columns:
        errors.append(f"Missing taxi column: {taxi_column}")
        return {"valid": False, "errors": errors, "warnings": warnings, "taxi_reports": taxi_reports, "dataframe": result}

    empty_taxi = result[taxi_column].isna() | (result[taxi_column].astype(str).str.strip() == "")
    if empty_taxi.any():
        errors.append(f"{int(empty_taxi.sum())} rows have empty taxi values.")

    duplicate_key_cols = [col for col in ["Date", "Matricule", "Nom - Prénom", "Nom - Prenom", "Adresse"] if col in result.columns]
    if duplicate_key_cols:
        duplicated = result.duplicated(subset=duplicate_key_cols, keep=False)
        if duplicated.any():
            warnings.append(f"{int(duplicated.sum())} rows look duplicated by {', '.join(duplicate_key_cols)}.")

    for taxi, group in result.groupby(taxi_column, sort=False, dropna=False):
        taxi_errors: list[str] = []
        taxi_warnings: list[str] = []
        date_col = _find_existing_col(group, ["Date"])
        if date_col is not None:
            parsed_dates = _parse_dispatch_dates(group[date_col], day_first=day_first)
            if parsed_dates.isna().any():
                taxi_errors.append("contains missing or invalid date")
            dates = sorted(parsed_dates.dropna().dt.strftime("%Y-%m-%d").unique().tolist())
            if len(dates) > 1:
                taxi_errors.append(f"contains multiple dates: {', '.join(dates)}")
        dispatch_id_col = _find_source_dispatch_id_column(group)
        if dispatch_id_col is not None:
            dispatch_ids = group[dispatch_id_col].map(_clean_source_dispatch_id)
            if dispatch_ids.isna().any():
                taxi_errors.append("contains missing source dispatch id")
            source_ids = sorted(dispatch_ids.dropna().unique().tolist())
            if len(source_ids) > 1:
                taxi_errors.append(f"contains multiple source dispatch ids: {', '.join(source_ids)}")
        zones = sorted(str(z) for z in group.get("Zone", pd.Series(dtype=str)).dropna().unique())
        destinations = sorted(str(z) for z in group.get("DetectedDestination", pd.Series(dtype=str)).dropna().unique())
        times = sorted(str(z) for z in _series_for_candidates(group, ["Heure d'arrivée", "Heure d'arrivee", "Heure", "Heure de départ"]).dropna().unique())
        dispatch_types = sorted(str(z) for z in _series_for_candidates(group, ["Dispatch Type", "Type de course", "Ramassage / Retour"]).dropna().unique())

        if len(group) > capacity:
            taxi_errors.append(f"contains {len(group)} agents, maximum is {capacity}")
        if len(times) > 1:
            taxi_errors.append(f"contains multiple times: {', '.join(times)}")
        if len(dispatch_types) > 1:
            taxi_errors.append(f"contains multiple dispatch types: {', '.join(dispatch_types)}")
        if UNKNOWN_ZONE in zones and len(zones) > 1:
            taxi_errors.append("mixes UNKNOWN addresses with known zones")
        if UNKNOWN_ZONE in zones:
            taxi_warnings.append("contains UNKNOWN address")
        if not _zones_list_compatible(zones):
            taxi_errors.append(f"contains incompatible zones: {', '.join(zones)}")
        if not _destinations_list_compatible(destinations):
            taxi_errors.append(f"contains incompatible destinations: {', '.join(destinations)}")

        status = "INVALID" if taxi_errors else "WARNING" if taxi_warnings else "VALID"
        message = "; ".join(taxi_errors + taxi_warnings)
        if taxi_errors:
            errors.append(f"Taxi {taxi} invalid: {message}.")
        elif taxi_warnings:
            warnings.append(f"Taxi {taxi} warning: {message}.")

        result.loc[group.index, "ValidationStatus"] = status
        result.loc[group.index, "ValidationMessage"] = message
        taxi_reports.append(
            {
                "Taxi": taxi,
                "Agents count": len(group),
                "Zones inside taxi": ", ".join(zones),
                "Destinations inside taxi": ", ".join(destinations),
                "Times inside taxi": ", ".join(times),
                "Validation status": status,
                "Error message": message,
                "Group reason": ", ".join(sorted(str(x) for x in group.get("GroupReason", pd.Series(dtype=str)).dropna().unique())),
            }
        )

    non_empty = _drop_empty_agent_rows(result)
    if len(non_empty) != len(result):
        errors.append(f"{len(result) - len(non_empty)} empty agent rows are present in dispatch output.")
    matricule_col = _find_existing_col(result, ["Matricule"])
    if matricule_col:
        values = result[matricule_col].astype(str).str.strip()
        values = values[values != ""]
        duplicated_matricules = values[values.duplicated(keep=False)]
        if not duplicated_matricules.empty:
            errors.append(f"Duplicated matricules found: {sorted(duplicated_matricules.unique())[:20]}")
    if len(result) and taxi_reports:
        theoretical_min = (len(result) + capacity - 1) // capacity
        if len(taxi_reports) > max(theoretical_min * 2, theoretical_min + 8):
            warnings.append(f"Taxi count looks high: {len(taxi_reports)} taxis for {len(result)} agents. Theoretical minimum is {theoretical_min}.")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "taxi_reports": taxi_reports,
        "dataframe": result,
    }


def _series_for_candidates(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    normalized = {_normalize_col(col): col for col in df.columns}
    for candidate in candidates:
        col = normalized.get(_normalize_col(candidate))
        if col:
            return df[col]
    return pd.Series(dtype=str)


def _find_existing_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    normalized = {_normalize_col(col): col for col in df.columns}
    for candidate in candidates:
        found = normalized.get(_normalize_col(candidate))
        if found:
            return found
    return None


def _normalize_col(value: object) -> str:
    return str(value).lower().replace("é", "e").replace("è", "e").replace("Ã©", "e").replace("Ã¨", "e").strip()


def _zones_list_compatible(zones: list[str]) -> bool:
    clean = [zone for zone in zones if zone]
    if UNKNOWN_ZONE in clean:
        return len(set(clean)) == 1
    return all(zones_are_compatible(a, b) for a, b in combinations(clean, 2))


def _destinations_list_compatible(destinations: list[str]) -> bool:
    clean = [destination for destination in destinations if destination and destination != UNKNOWN_ZONE]
    return all(_destinations_are_compatible(a, b) for a, b in combinations(clean, 2))


def validate_groups(df: pd.DataFrame, taxi_column: str = TAXI_COLUMN, capacity: int = MAX_TAXI_CAPACITY) -> None:
    """Backward-compatible validator used by existing CLI/UI code."""
    validation = validate_dispatch(df, taxi_column=taxi_column, capacity=capacity)
    if validation["errors"]:
        raise ValueError("\n".join(validation["errors"]))
