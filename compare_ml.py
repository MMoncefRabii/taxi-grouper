"""
Compare taxi grouping output with ML enabled and disabled.
"""

import pandas as pd
from src.core.preprocessing import load_dispatch_excel, detect_columns, filter_dataframe
from src.core.grouper import group_agents
import time

TEST_FILE = "test_ramassage.xlsx"


def main():
    df = load_dispatch_excel(TEST_FILE)
    columns = detect_columns(df)
    df_filtered = filter_dataframe(df, columns, time_value=None, type_course=None, operation=None)
    print(f"Filtered rows: {len(df_filtered)}")

    start = time.time()
    grouped_ml, warnings_ml = group_agents(df_filtered, columns=columns, use_ml=True)
    ml_duration = time.time() - start
    start = time.time()
    grouped_no_ml, warnings_no_ml = group_agents(df_filtered, columns=columns, use_ml=False)
    no_ml_duration = time.time() - start

    print(f"use_ml=True warnings: {warnings_ml}")
    print(f"use_ml=False warnings: {warnings_no_ml}")
    print(f"use_ml=True duration: {ml_duration:.2f}s")
    print(f"use_ml=False duration: {no_ml_duration:.2f}s")
    print(f"use_ml=True taxi count: {grouped_ml['Groupe Taxi'].nunique()}\nuse_ml=False taxi count: {grouped_no_ml['Groupe Taxi'].nunique()}")

    # Compare taxi numbers and key columns
    compare = pd.DataFrame({
        "index": grouped_ml.index,
        "name": grouped_ml.get("Nom - Prénom", grouped_ml.get("Nom", "")),
        "address": grouped_ml.get("Adresse", grouped_ml.get("Destination", grouped_ml.get("Adresse_att", ""))),
        "use_ml_taxi": grouped_ml["Groupe Taxi"].astype(str),
        "no_ml_taxi": grouped_no_ml["Groupe Taxi"].astype(str),
        "destination": grouped_ml.get("DetectedDestination", ""),
        "zone": grouped_ml.get("DestinationZone", ""),
    })
    compare["different"] = compare["use_ml_taxi"] != compare["no_ml_taxi"]
    diff_count = int(compare["different"].sum())
    print(f"Rows with different taxi assignments: {diff_count}")

    if diff_count:
        print(compare[compare["different"]].head(40).to_string(index=False))

    # Show grouping summary for both
    print("\nSummary use_ml=True:\n", grouped_ml.groupby(["Groupe Taxi"]).size().head(10))
    print("\nSummary use_ml=False:\n", grouped_no_ml.groupby(["Groupe Taxi"]).size().head(10))

    compare.to_csv("ml_vs_no_ml_comparison.csv", index=False)
    print("Saved comparison CSV to ml_vs_no_ml_comparison.csv")


if __name__ == "__main__":
    main()
