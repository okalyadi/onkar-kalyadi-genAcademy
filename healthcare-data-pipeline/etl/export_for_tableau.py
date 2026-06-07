import os
import pandas as pd
from sqlalchemy import create_engine
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DB_URL = (
    f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)
OUT_DIR = Path(__file__).parent.parent / "data/tableau"
OUT_DIR.mkdir(parents=True, exist_ok=True)

QUERIES = {
    "overview": """
        SELECT
            COUNT(*)                        AS total_patients,
            ROUND(SUM(billing_amount), 2)   AS total_revenue,
            ROUND(AVG(billing_amount), 2)   AS avg_billing_per_patient,
            ROUND(AVG(length_of_stay), 1)   AS avg_length_of_stay
        FROM patients
    """,

    "revenue_by_condition": """
        SELECT
            medical_condition,
            COUNT(*)                        AS patient_count,
            ROUND(SUM(billing_amount), 2)   AS total_revenue,
            ROUND(AVG(billing_amount), 2)   AS avg_billing,
            ROUND(AVG(length_of_stay), 1)   AS avg_length_of_stay
        FROM patients
        GROUP BY medical_condition
        ORDER BY total_revenue DESC
    """,

    "revenue_by_insurance": """
        SELECT
            insurance_provider,
            COUNT(*)                        AS patient_count,
            ROUND(SUM(billing_amount), 2)   AS total_revenue,
            ROUND(AVG(billing_amount), 2)   AS avg_billing
        FROM patients
        GROUP BY insurance_provider
        ORDER BY total_revenue DESC
    """,

    "admission_type_breakdown": """
        SELECT
            admission_type,
            COUNT(*)                                            AS patient_count,
            ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct_of_total,
            ROUND(AVG(billing_amount), 2)                       AS avg_billing,
            ROUND(AVG(length_of_stay), 1)                       AS avg_length_of_stay
        FROM patients
        GROUP BY admission_type
        ORDER BY patient_count DESC
    """,

    "monthly_trend": """
        SELECT
            DATE_TRUNC('month', date_of_admission)  AS month,
            COUNT(*)                                AS admissions,
            ROUND(SUM(billing_amount), 2)           AS monthly_revenue
        FROM patients
        GROUP BY month
        ORDER BY month
    """,

    "top_hospitals": """
        SELECT
            hospital,
            COUNT(*)                        AS patient_count,
            ROUND(SUM(billing_amount), 2)   AS total_revenue,
            ROUND(AVG(billing_amount), 2)   AS avg_billing
        FROM patients
        GROUP BY hospital
        ORDER BY total_revenue DESC
        LIMIT 10
    """,

    "length_of_stay_by_condition": """
        SELECT
            admission_type,
            medical_condition,
            COUNT(*)                        AS patient_count,
            ROUND(AVG(length_of_stay), 1)   AS avg_length_of_stay,
            MIN(length_of_stay)             AS min_stay,
            MAX(length_of_stay)             AS max_stay
        FROM patients
        GROUP BY admission_type, medical_condition
        ORDER BY avg_length_of_stay DESC
    """,

    "test_results": """
        SELECT
            test_results,
            COUNT(*)                                            AS patient_count,
            ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct_of_total,
            ROUND(AVG(billing_amount), 2)                       AS avg_billing
        FROM patients
        GROUP BY test_results
        ORDER BY patient_count DESC
    """,

    "age_group_analysis": """
        SELECT
            CASE
                WHEN age < 18  THEN 'Under 18'
                WHEN age < 35  THEN '18-34'
                WHEN age < 50  THEN '35-49'
                WHEN age < 65  THEN '50-64'
                ELSE '65+'
            END                             AS age_group,
            COUNT(*)                        AS patient_count,
            ROUND(AVG(billing_amount), 2)   AS avg_billing,
            ROUND(AVG(length_of_stay), 1)   AS avg_length_of_stay
        FROM patients
        GROUP BY age_group
        ORDER BY MIN(age)
    """,

    "top_doctors": """
        SELECT
            doctor,
            COUNT(*)                        AS patient_count,
            ROUND(SUM(billing_amount), 2)   AS total_revenue,
            ROUND(AVG(billing_amount), 2)   AS avg_billing
        FROM patients
        GROUP BY doctor
        ORDER BY patient_count DESC
        LIMIT 10
    """,
}


def run():
    engine = create_engine(DB_URL)
    for name, query in QUERIES.items():
        df = pd.read_sql(query, engine)
        path = OUT_DIR / f"{name}.csv"
        df.to_csv(path, index=False)
        print(f"Exported {name}.csv ({len(df)} rows)")
    print(f"\nAll files saved to: {OUT_DIR}")


if __name__ == "__main__":
    run()
