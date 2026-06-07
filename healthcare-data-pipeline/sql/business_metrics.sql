-- ============================================================
-- HEALTHCARE BUSINESS METRICS
-- ============================================================

-- 1. Total patients and total revenue
SELECT
    COUNT(*)                        AS total_patients,
    ROUND(SUM(billing_amount), 2)   AS total_revenue,
    ROUND(AVG(billing_amount), 2)   AS avg_billing_per_patient
FROM patients;


-- 2. Revenue and patient volume by medical condition
SELECT
    medical_condition,
    COUNT(*)                        AS patient_count,
    ROUND(SUM(billing_amount), 2)   AS total_revenue,
    ROUND(AVG(billing_amount), 2)   AS avg_billing,
    ROUND(AVG(length_of_stay), 1)   AS avg_length_of_stay
FROM patients
GROUP BY medical_condition
ORDER BY total_revenue DESC;


-- 3. Revenue and volume by insurance provider
SELECT
    insurance_provider,
    COUNT(*)                        AS patient_count,
    ROUND(SUM(billing_amount), 2)   AS total_revenue,
    ROUND(AVG(billing_amount), 2)   AS avg_billing
FROM patients
GROUP BY insurance_provider
ORDER BY total_revenue DESC;


-- 4. Admission type breakdown
SELECT
    admission_type,
    COUNT(*)                                            AS patient_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct_of_total,
    ROUND(AVG(billing_amount), 2)                       AS avg_billing,
    ROUND(AVG(length_of_stay), 1)                       AS avg_length_of_stay
FROM patients
GROUP BY admission_type
ORDER BY patient_count DESC;


-- 5. Monthly admissions and revenue trend
SELECT
    DATE_TRUNC('month', date_of_admission)  AS month,
    COUNT(*)                                AS admissions,
    ROUND(SUM(billing_amount), 2)           AS monthly_revenue
FROM patients
GROUP BY month
ORDER BY month;


-- 6. Top 10 hospitals by revenue
SELECT
    hospital,
    COUNT(*)                        AS patient_count,
    ROUND(SUM(billing_amount), 2)   AS total_revenue,
    ROUND(AVG(billing_amount), 2)   AS avg_billing
FROM patients
GROUP BY hospital
ORDER BY total_revenue DESC
LIMIT 10;


-- 7. Average length of stay by admission type and condition
SELECT
    admission_type,
    medical_condition,
    COUNT(*)                        AS patient_count,
    ROUND(AVG(length_of_stay), 1)   AS avg_length_of_stay,
    MIN(length_of_stay)             AS min_stay,
    MAX(length_of_stay)             AS max_stay
FROM patients
GROUP BY admission_type, medical_condition
ORDER BY avg_length_of_stay DESC;


-- 8. Test results distribution
SELECT
    test_results,
    COUNT(*)                                            AS patient_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct_of_total,
    ROUND(AVG(billing_amount), 2)                       AS avg_billing
FROM patients
GROUP BY test_results
ORDER BY patient_count DESC;


-- 9. Age group analysis
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
ORDER BY MIN(age);


-- 10. Top doctors by patient volume and revenue
SELECT
    doctor,
    COUNT(*)                        AS patient_count,
    ROUND(SUM(billing_amount), 2)   AS total_revenue,
    ROUND(AVG(billing_amount), 2)   AS avg_billing
FROM patients
GROUP BY doctor
ORDER BY patient_count DESC
LIMIT 10;
