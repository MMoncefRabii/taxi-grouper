"""
Profile individual grouping stages to identify where the slowdown is.
"""
import time
from src.core.preprocessing import load_dispatch_excel, detect_columns, filter_dataframe
from src.core.grouper import group_agents


def profile_grouping_stages():
    df = load_dispatch_excel("test_ramassage.xlsx")
    cols = detect_columns(df)
    df_filtered = filter_dataframe(df, cols, time_value=None, type_course=None, operation=None)
    
    print(f"Profiling on {len(df_filtered)} rows\n")
    
    # Test use_ml=False (no ML, just rules)
    print("=== use_ml=False (rule-based only) ===")
    start = time.time()
    grouped_no_ml, _ = group_agents(df_filtered, columns=cols, use_ml=False)
    elapsed_no_ml = time.time() - start
    print(f"Time: {elapsed_no_ml:.2f}s\n")
    
    # Test use_ml=True (rules + ML scoring)
    print("=== use_ml=True (rules + ML scoring) ===")
    start = time.time()
    grouped_ml, _ = group_agents(df_filtered, columns=cols, use_ml=True)
    elapsed_ml = time.time() - start
    print(f"Time: {elapsed_ml:.2f}s\n")
    
    print(f"ML overhead: {elapsed_ml - elapsed_no_ml:.2f}s ({100 * (elapsed_ml - elapsed_no_ml) / elapsed_no_ml:.1f}% slowdown)")


if __name__ == "__main__":
    profile_grouping_stages()
