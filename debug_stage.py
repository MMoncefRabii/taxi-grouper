"""
Minimal stage-by-stage timing for the Taxi Grouper pipeline.

Run with:
    python debug_stage.py
"""

import time
from src.core.preprocessing import load_dispatch_excel, detect_columns, filter_dataframe
from src.core.grouper import group_agents, validate_dispatch
from src.config import TAXI_COLUMN, MAX_TAXI_CAPACITY

TEST_FILE = "test_ramassage.xlsx"


def main():
    print("Loading Excel...")
    t0 = time.perf_counter()
    df = load_dispatch_excel(TEST_FILE)
    print("  load_dispatch_excel", time.perf_counter() - t0)

    print("Detecting columns...")
    t0 = time.perf_counter()
    columns = detect_columns(df)
    print("  detect_columns", time.perf_counter() - t0)

    print("Filtering data...")
    t0 = time.perf_counter()
    df_filtered = filter_dataframe(df, columns, time_value=None, type_course=None, operation=None)
    print("  filter_dataframe", time.perf_counter() - t0)
    print("  rows after filter", len(df_filtered))

    print("Grouping with use_ml=True...")
    t0 = time.perf_counter()
    grouped, warnings = group_agents(df_filtered, columns=columns, use_ml=True)
    print("  group_agents", time.perf_counter() - t0)
    print("  grouped rows", len(grouped), "warnings", len(warnings))

    print("Validating...")
    t0 = time.perf_counter()
    validation = validate_dispatch(grouped, TAXI_COLUMN, MAX_TAXI_CAPACITY)
    print("  validate_dispatch", time.perf_counter() - t0)
    print("  valid", validation["valid"])

    print("Done.")


if __name__ == "__main__":
    main()
