import os
import pandas as pd
from sqlalchemy import create_engine, text
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

CLEAN_PATH = Path(__file__).parent.parent / "data/clean/healthcare_clean.csv"
DB_URL = (
    f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)
TABLE = "patients"


def create_table(engine):
    with engine.connect() as conn:
        conn.execute(text(f"""
            DROP TABLE IF EXISTS {TABLE};
            CREATE TABLE {TABLE} (
                id               SERIAL PRIMARY KEY,
                name             TEXT,
                age              INTEGER,
                gender           TEXT,
                blood_type       TEXT,
                medical_condition TEXT,
                date_of_admission DATE,
                discharge_date    DATE,
                length_of_stay    INTEGER,
                admission_type    TEXT,
                doctor            TEXT,
                hospital          TEXT,
                room_number       INTEGER,
                insurance_provider TEXT,
                billing_amount    NUMERIC(10, 2),
                medication        TEXT,
                test_results      TEXT
            );
        """))
        conn.commit()
    print(f"Table '{TABLE}' created.")


def load(engine):
    df = pd.read_csv(CLEAN_PATH, parse_dates=["Date of Admission", "Discharge Date"])
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    df.to_sql(TABLE, engine, if_exists="append", index=False, method="multi", chunksize=1000)
    print(f"Loaded {len(df):,} rows into '{TABLE}'.")


def verify(engine):
    with engine.connect() as conn:
        count = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar()
        sample = conn.execute(text(f"SELECT * FROM {TABLE} LIMIT 3")).fetchall()
    print(f"\nRow count in DB: {count:,}")
    print("Sample rows:")
    for row in sample:
        print(" ", row)


if __name__ == "__main__":
    engine = create_engine(DB_URL)
    print("--- Creating table ---")
    create_table(engine)
    print("\n--- Loading data ---")
    load(engine)
    print("\n--- Verifying ---")
    verify(engine)
