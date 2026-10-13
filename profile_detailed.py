"""
Detailed profiling of grouping substeps to identify the ML bottleneck.
"""
import time
from src.core.preprocessing import load_dispatch_excel, detect_columns, filter_dataframe
from src.core.destination_cleaner import add_clean_destination_columns
from src.core.grouper import group_agents
from src.core.ml_model import load_model


def profile_detailed():
    df = load_dispatch_excel("test_ramassage.xlsx")
    cols = detect_columns(df)
    df_filtered = filter_dataframe(df, cols, time_value=None, type_course=None, operation=None)
    
    print("Detailed profiling of grouping pipeline\n")
    
    # Step 1: Destination detection
    start = time.time()
    enriched = add_clean_destination_columns(df_filtered, cols.address, save_unknown=False)
    dest_time = time.time() - start
    print(f"1. Destination detection: {dest_time:.2f}s")
    
    # Step 2: Load model
    start = time.time()
    model = load_model()
    model_load_time = time.time() - start
    print(f"2. Model load: {model_load_time:.2f}s")
    
    # Step 3: Full grouping without ML
    start = time.time()
    grouped_no_ml, _ = group_agents(enriched, columns=cols, use_ml=False)
    no_ml_time = time.time() - start
    print(f"3. Grouping rule-based (no ML): {no_ml_time:.2f}s")
    
    # Step 4: Full grouping with ML
    start = time.time()
    grouped_ml, _ = group_agents(enriched, columns=cols, use_ml=True)
    ml_time = time.time() - start
    print(f"4. Grouping with ML: {ml_time:.2f}s")
    
    print(f"\nML overhead: {ml_time - no_ml_time:.2f}s")
    print(f"Total (without dest detection): {no_ml_time + (ml_time - no_ml_time):.2f}s")


if __name__ == "__main__":
    profile_detailed()
