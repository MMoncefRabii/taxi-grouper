"""
Instrumented timing to find the exact bottleneck in group_agents.
Patches taxi_grouper.grouper with timing prints.

Run with:
    python debug_instrumented.py
"""

import time
from src.core.preprocessing import load_dispatch_excel, detect_columns, filter_dataframe
from src.config import TAXI_COLUMN, MAX_TAXI_CAPACITY
from src.core import grouper

TEST_FILE = "test_ramassage.xlsx"

# Monkey-patch the slow functions to add timing
_original_enrich_zones = grouper.enrich_zones


def timed_enrich_zones(df, address_col):
    t0 = time.perf_counter()
    result = _original_enrich_zones(df, address_col)
    print(f"  [enrich_zones] {time.perf_counter() - t0:.2f}s for {len(df)} rows")
    return result


_original_group_block = grouper._group_block


def timed_group_block(df, block_indices, columns, model, capacity):
    t0 = time.perf_counter()
    result = _original_group_block(df, block_indices, columns, model, capacity)
    print(f"  [_group_block] {time.perf_counter() - t0:.2f}s for {len(block_indices)} block indices")
    return result


_original_ml_sort = grouper._ml_sort


def timed_ml_sort(indices, df, columns, model, anchor_indices=None):
    t0 = time.perf_counter()
    result = _original_ml_sort(indices, df, columns, model, anchor_indices)
    print(f"    [_ml_sort] {time.perf_counter() - t0:.2f}s for {len(indices)} indices")
    return result


# Install patches
grouper.enrich_zones = timed_enrich_zones
grouper._group_block = timed_group_block
grouper._ml_sort = timed_ml_sort


def main():
    print("Loading test data...")
    df = load_dispatch_excel(TEST_FILE)
    columns = detect_columns(df)
    df_filtered = filter_dataframe(df, columns, time_value=None, type_course=None, operation=None)
    print(f"Loaded {len(df_filtered)} rows\n")

    print("Running group_agents(use_ml=True)...")
    t0 = time.perf_counter()
    grouped, warnings = grouper.group_agents(df_filtered, columns=columns, use_ml=True)
    total = time.perf_counter() - t0

    print(f"\nTotal time: {total:.2f}s")
    print(f"Result: {len(grouped)} rows grouped, {len(warnings)} warnings")


if __name__ == "__main__":
    main()
