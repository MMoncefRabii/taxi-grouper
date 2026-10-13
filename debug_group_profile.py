"""
Targeted cProfile for group_agents specifically to find the bottleneck.

Run with:
    python debug_group_profile.py
"""

import cProfile
import pstats
import time
from io import StringIO

from src.core.preprocessing import load_dispatch_excel, detect_columns, filter_dataframe
from src.core.grouper import group_agents
from src.config import TAXI_COLUMN

TEST_FILE = "test_ramassage.xlsx"


def profile_grouping():
    print("Loading test data...")
    df = load_dispatch_excel(TEST_FILE)
    columns = detect_columns(df)
    df_filtered = filter_dataframe(df, columns, time_value=None, type_course=None, operation=None)
    print(f"Loaded {len(df_filtered)} rows for grouping")

    # Profile group_agents(use_ml=True)
    print("\n=== PROFILING group_agents(use_ml=True) ===")
    profiler = cProfile.Profile()
    profiler.enable()

    t0 = time.perf_counter()
    grouped, warnings = group_agents(df_filtered, columns=columns, use_ml=True)
    t1 = time.perf_counter()

    profiler.disable()

    print(f"Total time: {t1 - t0:.2f} seconds")

    # Print top 30 by cumulative time
    stats = pstats.Stats(profiler)
    stats.strip_dirs()
    stats.sort_stats("cumulative")

    print("\nTop 30 functions by cumulative time:")
    print("-" * 100)
    stats.print_stats(30)

    return grouped, warnings


if __name__ == "__main__":
    grouped, warnings = profile_grouping()
    print(f"\nResult: {len(grouped)} rows grouped, {len(warnings)} warnings")
