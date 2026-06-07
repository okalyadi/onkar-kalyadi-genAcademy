import pandas as pd
import numpy as np
import os
from pathlib import Path

RAW_PATH = Path(__file__).parent.parent / "data/raw/healthcare_dataset.csv"
CLEAN_PATH = Path(__file__).parent.parent / "data/clean/healthcare_clean.csv"


def load(path):
    df = pd.read_csv(path)
    print(f"Loaded {len(df):,} rows, {len(df.columns)} columns")
    return df


def clean(df):
    # Fix inconsistent casing in text columns
    text_cols = ["Name", "Gender", "Blood Type", "Medical Condition",
                 "Doctor", "Hospital", "Insurance Provider",
                 "Admission Type", "Medication", "Test Results"]
    for col in text_cols:
        df[col] = df[col].str.strip().str.title()

    # Parse dates
    df["Date of Admission"] = pd.to_datetime(df["Date of Admission"])
    df["Discharge Date"] = pd.to_datetime(df["Discharge Date"])

    # Derived column: length of stay in days
    df["Length of Stay"] = (df["Discharge Date"] - df["Date of Admission"]).dt.days

    # Round billing amount to 2 decimal places
    df["Billing Amount"] = df["Billing Amount"].round(2)

    # Ensure numeric types
    df["Age"] = pd.to_numeric(df["Age"], errors="coerce").astype("Int64")
    df["Room Number"] = pd.to_numeric(df["Room Number"], errors="coerce").astype("Int64")

    # Drop rows with nulls in critical columns
    critical = ["Name", "Age", "Gender", "Date of Admission", "Discharge Date", "Billing Amount"]
    before = len(df)
    df = df.dropna(subset=critical)
    dropped = before - len(df)
    if dropped:
        print(f"Dropped {dropped} rows with nulls in critical columns")

    # Drop duplicates
    before = len(df)
    df = df.drop_duplicates()
    dupes = before - len(df)
    if dupes:
        print(f"Dropped {dupes} duplicate rows")

    # Reorder columns
    df = df[[
        "Name", "Age", "Gender", "Blood Type", "Medical Condition",
        "Date of Admission", "Discharge Date", "Length of Stay",
        "Admission Type", "Doctor", "Hospital", "Room Number",
        "Insurance Provider", "Billing Amount", "Medication", "Test Results"
    ]]

    return df


def save(df, path):
    os.makedirs(path.parent, exist_ok=True)
    df.to_csv(path, index=False)
    print(f"Saved clean data to {path} ({len(df):,} rows)")


def run():
    print("--- ETL: Extract ---")
    df = load(RAW_PATH)

    print("\n--- ETL: Transform ---")
    df = clean(df)

    print("\n--- ETL: Load (file) ---")
    save(df, CLEAN_PATH)

    print("\n--- Preview ---")
    print(df.head(3).to_string())
    print(f"\nLength of Stay stats:\n{df['Length of Stay'].describe()}")


if __name__ == "__main__":
    run()
