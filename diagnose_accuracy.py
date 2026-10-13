"""
Diagnostic script to analyze destination detection accuracy on test_ramassage.xlsx.
Shows unknown vs detected destination breakdown with current single-scorer (token_set_ratio) approach.
"""
from pathlib import Path
import pandas as pd
from src.core.preprocessing import load_dispatch_excel, detect_columns, filter_dataframe
from src.core.destination_cleaner import add_clean_destination_columns, validate_cleaned_destinations


def analyze_destination_accuracy(file_path: str):
    df = load_dispatch_excel(file_path)
    cols = detect_columns(df)
    df_filtered = filter_dataframe(df, cols, time_value=None, type_course=None, operation=None)
    
    print(f"Total rows: {len(df_filtered)}\n")
    
    # Add destination detection columns
    result = add_clean_destination_columns(df_filtered, cols.address, save_unknown=False)
    
    # Analyze results
    validation = validate_cleaned_destinations(result)
    
    print("=== CURRENT IMPLEMENTATION (single token_set_ratio scorer) ===")
    print(f"Unknown destinations: {validation['unknown_destinations']}")
    print(f"Low-confidence (needs manual): {validation['needs_manual_validation']}")
    print(f"Valid (>=85 confidence): {len(result) - validation['unknown_destinations'] - validation['needs_manual_validation']}")
    print()
    
    # Show breakdown by status
    print("Status breakdown:")
    status_counts = result['DestinationStatus'].value_counts()
    for status, count in status_counts.items():
        print(f"  {status}: {count}")
    print()
    
    # Show sample unknowns
    unknowns = result[result['DestinationStatus'] == 'unknown']
    print(f"Sample unknown addresses ({min(5, len(unknowns))} of {len(unknowns)}):")
    for idx, row in unknowns.head(5).iterrows():
        print(f"  - {row['CleanAddress']}")


if __name__ == "__main__":
    analyze_destination_accuracy("test_ramassage.xlsx")
