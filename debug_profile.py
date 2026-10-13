"""
Standalone profiling script for the Taxi Grouper pipeline.

Run directly with:
    python debug_profile.py

It uses the same pipeline stages as api.py, but bypasses FastAPI/uvicorn.
"""

import cProfile
import json
import tempfile
import time
from pathlib import Path
import pstats

import pandas as pd

from src.core.preprocessing import load_dispatch_excel, detect_columns, filter_dataframe
from src.core.grouper import group_agents, validate_dispatch, enrich_zones
from src.config import TAXI_COLUMN, MAX_TAXI_CAPACITY, UNKNOWN_ZONE

TEST_FILE = Path(__file__).resolve().parent / "test_ramassage.xlsx"


def time_stage(name: str, func, *args, **kwargs):
    start = time.perf_counter()
    result = func(*args, **kwargs)
    end = time.perf_counter()
    duration = end - start
    print(f"{name}: {duration:.4f} seconds")
    return result, duration


def run_pipeline(use_ml: bool) -> dict:
    print("\n" + "=" * 80)
    print(f"Running pipeline: use_ml={use_ml}")
    print("=" * 80)

    timings = {}

    if not TEST_FILE.exists():
        raise FileNotFoundError(f"Test file not found: {TEST_FILE}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as temp_handle:
        temp_path = Path(temp_handle.name)
        temp_handle.write(TEST_FILE.read_bytes())

    try:
        df, timings["load_excel"] = time_stage("load_dispatch_excel", load_dispatch_excel, str(temp_path))

        columns, timings["detect_columns"] = time_stage("detect_columns", detect_columns, df)

        df_filtered, timings["filter_dataframe"] = time_stage(
            "filter_dataframe",
            filter_dataframe,
            df,
            columns,
            time_value=None,
            type_course=None,
            operation=None,
        )

        enriched, timings["enrich_zones"] = time_stage("enrich_zones", enrich_zones, df_filtered, columns.address)

        grouped, timings["group_agents"] = time_stage("group_agents", group_agents, df_filtered, columns=columns, use_ml=use_ml)

        validation, timings["validate_dispatch"] = time_stage(
            "validate_dispatch",
            validate_dispatch,
            grouped,
            TAXI_COLUMN,
            MAX_TAXI_CAPACITY,
        )

        stats = {
            "total_agents": len(grouped),
            "total_taxis": int(grouped[TAXI_COLUMN].max()) if TAXI_COLUMN in grouped.columns else 0,
            "unknown_count": int((grouped.get("Zone", pd.Series()) == UNKNOWN_ZONE).sum()),
        }

        print("\nPipeline statistics:")
        print(json.dumps({**stats, **timings}, indent=2))

        return {
            "use_ml": use_ml,
            "timings": timings,
            "stats": stats,
            "validation": validation,
        }
    finally:
        if temp_path.exists():
            temp_path.unlink()


def profile_run(use_ml: bool):
    profile = cProfile.Profile()
    profile.enable()
    result = run_pipeline(use_ml)
    profile.disable()

    print("\nTop 20 functions by cumulative time:")
    stats = pstats.Stats(profile).strip_dirs().sort_stats("cumulative")
    stats.print_stats(20)

    return result


if __name__ == "__main__":
    print("Starting debug profile against test_ramassage.xlsx")
    results = []
    for use_ml in (True, False):
        results.append(profile_run(use_ml))

    print("\nSummary:")
    for result in results:
        print(f"use_ml={result['use_ml']}")
        for stage, duration in result["timings"].items():
            print(f"  {stage}: {duration:.4f} seconds")
        print(f"  total_agents: {result['stats']['total_agents']}")
        print(f"  total_taxis: {result['stats']['total_taxis']}")
        print(f"  unknown_count: {result['stats']['unknown_count']}")
        print(f"  valid: {result['validation']['valid']}")
        print()
