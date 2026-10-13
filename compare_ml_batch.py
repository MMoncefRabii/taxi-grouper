"""
Run ML vs no-ML grouping comparison on multiple Excel files.
If file paths are passed as arguments they will be used; otherwise
up to two `.xlsx` files will be discovered (excluding `test_ramassage.xlsx`).
"""
import argparse
import glob
import os
import time
from pathlib import Path

import pandas as pd

from src.core.preprocessing import load_dispatch_excel, detect_columns, filter_dataframe
from src.core.grouper import group_agents


def compare_file(path: str) -> dict:
    print(f"\n== Processing: {path}")
    df = load_dispatch_excel(path)
    columns = detect_columns(df)
    df_filtered = filter_dataframe(df, columns, time_value=None, type_course=None, operation=None)
    print(f"Filtered rows: {len(df_filtered)}")

    start = time.time()
    grouped_ml, warnings_ml = group_agents(df_filtered, columns=columns, use_ml=True)
    ml_duration = time.time() - start

    start = time.time()
    grouped_no_ml, warnings_no_ml = group_agents(df_filtered, columns=columns, use_ml=False)
    no_ml_duration = time.time() - start

    taxi_count_ml = int(grouped_ml['Groupe Taxi'].nunique()) if 'Groupe Taxi' in grouped_ml.columns else None
    taxi_count_no_ml = int(grouped_no_ml['Groupe Taxi'].nunique()) if 'Groupe Taxi' in grouped_no_ml.columns else None

    compare = pd.DataFrame({
        "index": grouped_ml.index,
        "use_ml_taxi": grouped_ml.get("Groupe Taxi", "").astype(str),
        "no_ml_taxi": grouped_no_ml.get("Groupe Taxi", "").astype(str),
    })
    compare['different'] = compare['use_ml_taxi'] != compare['no_ml_taxi']
    diff_count = int(compare['different'].sum())

    out_csv = Path(path).stem + "__ml_vs_no_ml.csv"
    compare.to_csv(out_csv, index=False)

    result = {
        "file": path,
        "rows": len(df_filtered),
        "ml_duration_s": ml_duration,
        "no_ml_duration_s": no_ml_duration,
        "warnings_ml": warnings_ml,
        "warnings_no_ml": warnings_no_ml,
        "taxi_count_ml": taxi_count_ml,
        "taxi_count_no_ml": taxi_count_no_ml,
        "diff_count": diff_count,
        "comparison_csv": str(out_csv),
    }
    print(f"use_ml=True duration: {ml_duration:.2f}s, use_ml=False duration: {no_ml_duration:.2f}s")
    print(f"Rows with different taxi assignments: {diff_count}")
    print(f"Saved comparison CSV: {out_csv}")
    return result


def discover_candidates(exclude: set[str] | None = None, limit: int = 2) -> list[str]:
    exclude = exclude or set()
    candidates = [p for p in glob.glob("**/*.xlsx", recursive=True) if os.path.basename(p) not in exclude]
    # prefer files in top-level and data/ and tests/
    candidates_sorted = sorted(candidates, key=lambda p: (0 if (os.path.dirname(p) == '' or p.startswith('data') or p.startswith('tests')) else 1, p))
    return candidates_sorted[:limit]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", help="Excel files to compare")
    args = parser.parse_args()

    if args.files:
        files = args.files
    else:
        candidates = discover_candidates(exclude={"test_ramassage.xlsx"}, limit=2)
        if not candidates:
            print("No candidate .xlsx files found to compare.")
            return
        files = candidates

    summary = []
    for f in files:
        try:
            summary.append(compare_file(f))
        except Exception as e:
            print(f"Error processing {f}: {e}")

    # Summarize
    print("\n=== Summary ===")
    for res in summary:
        print(f"{res['file']}: rows={res['rows']} diffs={res['diff_count']} ml={res['ml_duration_s']:.2f}s no_ml={res['no_ml_duration_s']:.2f}s csv={res['comparison_csv']}")


if __name__ == "__main__":
    main()
