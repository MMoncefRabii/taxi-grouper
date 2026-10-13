#!/usr/bin/env python3
"""Test the sequential color assignment in the backend by writing to a Google Sheet."""

import sys
import pandas as pd

# Add project root to path
sys.path.insert(0, '/c/Users/MSI/Desktop/taxi_grouper')

try:
    from src.data.sheets_repository import write_grouped_df_to_sheet
except ImportError as e:
    print(f"Error importing: {e}")
    print("Make sure to run from the project root with: python test_backend_colors.py")
    sys.exit(1)

# Create sample grouped data with 6 taxi groups (to test cycling through 10-color palette)
sample_data = [
    # Taxi 1 (group 1)
    {"Date": "2026-07-12", "Matricule": "T001", "Nom - Prénom": "Agent 1", "Opération": "Visit", 
     "Site": "Site A", "Numéro": "1", "Adresse": "123 Main St", "Heure d'arrivée": "09:00", 
     "Groupe Taxi": "1", "PRIX": "5.0"},
    # Taxi 2 (group 2) 
    {"Date": "2026-07-12", "Matricule": "T002", "Nom - Prénom": "Agent 2", "Opération": "Visit",
     "Site": "Site B", "Numéro": "2", "Adresse": "456 Oak Ave", "Heure d'arrivée": "09:15",
     "Groupe Taxi": "2", "PRIX": "5.5"},
    # Taxi 3 (group 3)
    {"Date": "2026-07-12", "Matricule": "T003", "Nom - Prénom": "Agent 3", "Opération": "Delivery",
     "Site": "Site C", "Numéro": "3", "Adresse": "789 Pine Rd", "Heure d'arrivée": "09:30",
     "Groupe Taxi": "3", "PRIX": "6.0"},
    # Taxi 4 (group 4)
    {"Date": "2026-07-12", "Matricule": "T004", "Nom - Prénom": "Agent 4", "Opération": "Visit",
     "Site": "Site D", "Numéro": "4", "Adresse": "321 Elm St", "Heure d'arrivée": "09:45",
     "Groupe Taxi": "4", "PRIX": "5.2"},
    # Taxi 5 (group 5)
    {"Date": "2026-07-12", "Matricule": "T005", "Nom - Prénom": "Agent 5", "Opération": "Visit",
     "Site": "Site E", "Numéro": "5", "Adresse": "654 Maple Ln", "Heure d'arrivée": "10:00",
     "Groupe Taxi": "5", "PRIX": "5.8"},
    # Taxi 6 (group 6)
    {"Date": "2026-07-12", "Matricule": "T006", "Nom - Prénom": "Agent 6", "Opération": "Delivery",
     "Site": "Site F", "Numéro": "6", "Adresse": "987 Cedar Dr", "Heure d'arrivée": "10:15",
     "Groupe Taxi": "6", "PRIX": "6.5"},
]

df = pd.DataFrame(sample_data)

print("=" * 70)
print("BACKEND SEQUENTIAL COLOR TEST")
print("=" * 70)
print("\nSample data to write to Google Sheet:")
print(df[["Matricule", "Nom - Prénom", "Groupe Taxi", "Adresse"]].to_string())

# This is the spreadsheet ID where test data will be written
# You need to use an actual Google Sheet ID that you have access to
SPREADSHEET_ID = "1O5K9a7d5l4KI11ntGzypTqD5cji6ny3RwThPM0S9wvI"

print(f"\nWriting to spreadsheet: {SPREADSHEET_ID}")
print("(The backend will apply sequential colors to the 'Cliente' sheet)")

try:
    result_url = write_grouped_df_to_sheet(SPREADSHEET_ID, df)
    print("\n✓ SUCCESS: Data written to Google Sheet!")
    print(f"Sheet URL: {result_url}")
    print("\nNEXT STEPS:")
    print("1. Open the URL above in your browser")
    print("2. Click on the 'Cliente' (client-facing) sheet tab")
    print("3. Verify that all 6 taxi groups have DIFFERENT background colors")
    print("4. Expected colors (in order):")
    colors = ["#F6D55C", "#ED553B", "#3CAEA3", "#20639B", "#173F5F", "#F66B9B"]
    for i, color in enumerate(colors, 1):
        print(f"   - Taxi {i}: {color}")
    
except Exception as e:
    print(f"\n✗ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
