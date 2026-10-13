"""
Isolate destination detection time to measure multi-scorer vs single-scorer overhead.
"""
import time
from src.core.preprocessing import load_dispatch_excel, detect_columns, filter_dataframe
from src.core.destination_cleaner import add_clean_destination_columns


def profile_destination_detection():
    df = load_dispatch_excel("test_ramassage.xlsx")
    cols = detect_columns(df)
    df_filtered = filter_dataframe(df, cols, time_value=None, type_course=None, operation=None)
    
    print(f"Profiling destination detection on {len(df_filtered)} rows\n")
    
    start = time.time()
    result = add_clean_destination_columns(df_filtered, cols.address, save_unknown=False)
    elapsed = time.time() - start
    
    print(f"Destination detection time: {elapsed:.2f}s")
    print(f"Unknown: {int((result['DestinationStatus'] == 'unknown').sum())}")
    print(f"Low-confidence: {int((result['DestinationStatus'] == 'needs_manual_validation').sum())}")
    print(f"Valid: {int((result['DestinationStatus'] == 'valid').sum())}")


if __name__ == "__main__":
    profile_destination_detection()
