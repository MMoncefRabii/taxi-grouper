from __future__ import annotations

import pandas as pd
from src.core.preprocessing import load_dispatch_excel, detect_columns, filter_dataframe
from src.core.grouper import group_agents, _ml_sort
from src.core import grouper

TEST_FILE = "test_ramassage.xlsx"


def _ml_sort_no_skip(indices, df, columns, model, anchor_indices=None):
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

    anchors = anchor_indices or indices

    pair_indices = []
    rows_a = []
    rows_b = []
    for idx in indices:
        for anchor in anchors:
            if anchor == idx or not grouper._pair_passes_hard_rules(df, idx, anchor):
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

    scores = grouper.score_pairs(model, rows_a, rows_b, columns)
    avg_scores = {}
    for idx, score in zip(pair_indices, scores):
        avg_scores.setdefault(idx, []).append(score)

    def key(idx: int) -> tuple[float, str, int]:
        candidate_scores = avg_scores.get(idx, [])
        avg_score = sum(candidate_scores) / len(candidate_scores) if candidate_scores else 0.0
        return (-avg_score, str(df.at[idx, "CleanAddress"]), int(df.at[idx, "_original_order"]))

    return sorted(indices, key=key)


def compare_assignments():
    df = load_dispatch_excel(TEST_FILE)
    columns = detect_columns(df)
    df_filtered = filter_dataframe(df, columns, time_value=None, type_course=None, operation=None)
    print(f"Filtered rows: {len(df_filtered)}")

    grouped_current, warnings_current = group_agents(df_filtered, columns=columns, use_ml=True)
    print("Current version (hybrid+ML-skip) warnings:", warnings_current)

    original_ml_sort = grouper._ml_sort
    try:
        grouper._ml_sort = _ml_sort_no_skip
        grouped_baseline, warnings_baseline = group_agents(df_filtered, columns=columns, use_ml=True)
    finally:
        grouper._ml_sort = original_ml_sort

    print("Baseline version (same code, ML-skip disabled) warnings:", warnings_baseline)
    if len(grouped_current) != len(grouped_baseline):
        raise RuntimeError("Grouped row counts differ between current and baseline versions.")

    compare = pd.DataFrame({
        "index": grouped_current.index,
        "name": grouped_current.get("Nom - Prénom", grouped_current.get("Nom", "")),
        "address": grouped_current.get("Adresse", grouped_current.get("Destination", grouped_current.get("Adresse_att", "")) ),
        "current_taxi": grouped_current["Groupe Taxi"].astype(str),
        "baseline_taxi": grouped_baseline["Groupe Taxi"].astype(str),
        "destination": grouped_current.get("DetectedDestination", ""),
        "zone": grouped_current.get("DestinationZone", ""),
        "group_reason_current": grouped_current.get("GroupReason", ""),
        "group_reason_baseline": grouped_baseline.get("GroupReason", ""),
        "rule_current": grouped_current.get("RuleUsed", ""),
        "rule_baseline": grouped_baseline.get("RuleUsed", ""),
    })
    compare["different"] = compare["current_taxi"] != compare["baseline_taxi"]
    diff_count = int(compare["different"].sum())
    print(f"Rows with different taxi assignments: {diff_count}")
    if diff_count > 0:
        out = compare[compare["different"]].copy()
        out = out.reset_index(drop=True)
        print(out.head(80).to_string(index=False))
        out.to_csv("ml_skip_assignment_differences.csv", index=False)
        print("Saved differences to ml_skip_assignment_differences.csv")
    else:
        print("No assignment differences found between current hybrid+ML-skip and baseline no-skip versions.")


if __name__ == "__main__":
    compare_assignments()
