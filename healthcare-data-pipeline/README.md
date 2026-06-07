# Healthcare Data Pipeline

End-to-end data engineering and analytics pipeline for a healthcare dataset.  
**Stack:** Python · PostgreSQL · SQL · Tableau Public  
**Live Dashboard:** [Healthcare Business Dashboard](https://public.tableau.com/app/profile/onkar.kalyadi1733/viz/HealthCareBusinessDashboard/HealthcareBusinessDashboard)

---

## Project Structure

```
data_pipeline/
├── data/
│   ├── raw/                  # Raw input CSV
│   ├── clean/                # Transformed output CSV
│   └── tableau/              # Aggregated CSVs for Tableau
├── etl/
│   ├── transform.py          # Extract & transform raw data
│   ├── load_to_postgres.py   # Load clean data into PostgreSQL
│   └── export_for_tableau.py # Export metric CSVs from PostgreSQL
├── sql/
│   └── business_metrics.sql  # Business KPI queries
├── docker-compose.yml
├── requirements.txt
└── .env
```

---

## Setup

### 1. Prerequisites
- Python 3.8+
- Docker Desktop

### 2. Install Python dependencies
```bash
pip3 install -r requirements.txt
```

### 3. Start PostgreSQL
```bash
docker-compose up -d
```

### 4. Add your dataset
Place the raw CSV in `data/raw/healthcare_dataset.csv`.

---

## Running the Pipeline

Run each step in order:

```bash
# Step 1 — Clean and transform the raw data
python3 etl/transform.py

# Step 2 — Load clean data into PostgreSQL
python3 etl/load_to_postgres.py

# Step 3 — Export aggregated metrics for Tableau
python3 etl/export_for_tableau.py
```

---

## Business Metrics (SQL)

Queries are in `sql/business_metrics.sql`. Run them directly:

```bash
docker exec -i healthcare_pg psql -U postgres -d healthcare < sql/business_metrics.sql
```

Metrics included:
- Total patients, revenue, avg billing
- Revenue & volume by medical condition
- Revenue by insurance provider
- Admission type breakdown
- Monthly admissions & revenue trend
- Top 10 hospitals by revenue
- Avg length of stay by condition and admission type
- Test results distribution
- Age group analysis
- Top 10 doctors by patient volume

---

## Tableau Dashboard

1. Download [Tableau Public](https://public.tableau.com)
2. Connect → **Text file** → load any CSV from `data/tableau/`
3. Suggested charts:

| File | Chart |
|---|---|
| `monthly_trend.csv` | Line — Monthly Revenue & Admissions |
| `revenue_by_condition.csv` | Bar — Revenue by Condition |
| `revenue_by_insurance.csv` | Bar — Revenue by Insurance Provider |
| `admission_type_breakdown.csv` | Pie — Admission Type Mix |
| `age_group_analysis.csv` | Bar — Patients by Age Group |
| `test_results.csv` | Pie — Test Results Distribution |
| `length_of_stay_by_condition.csv` | Heatmap — Avg Length of Stay |
| `top_hospitals.csv` | Horizontal Bar — Top 10 Hospitals |

---

## Database Connection

| Setting | Value |
|---|---|
| Host | localhost |
| Port | 5432 |
| Database | healthcare |
| User | postgres |
| Password | postgres |

---

## Stopping the Database

```bash
docker-compose down        # stop container (data persists)
docker-compose down -v     # stop and delete all data
```
