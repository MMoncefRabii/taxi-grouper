"""
Profile destination detection performance with multi-scorer implementation.
Measures end-to-end grouping time on test_ramassage.xlsx.
"""
import time
from src.core.preprocessing import load_dispatch_excel, detect_columns, filter_dataframe
from src.core.grouper import group_agents


def profile_grouping():
    df = load_dispatch_excel("test_ramassage.xlsx")
    cols = detect_columns(df)
    df_filtered = filter_dataframe(df, cols, time_value=None, type_course=None, operation=None)
    
    print(f"Profiling on {len(df_filtered)} rows\n")
    
    start = time.time()
    grouped, warnings = group_agents(df_filtered, columns=cols, use_ml=True)
    elapsed = time.time() - start
    
    print(f"Total grouping time (use_ml=True): {elapsed:.2f}s")
    print(f"Stats: {grouped['Groupe Taxi'].nunique()} taxis formed")
    
    start = time.time()
    grouped_no_ml, warnings = group_agents(df_filtered, columns=cols, use_ml=False)
    elapsed_no_ml = time.time() - start
    
    print(f"Total grouping time (use_ml=False): {elapsed_no_ml:.2f}s")
    
    return elapsed, elapsed_no_ml


if __name__ == "__main__":
    profile_grouping()
