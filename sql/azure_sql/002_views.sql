-- T-SQL views for the gold layer -- what the FastAPI/GraphQL service and the dashboard actually query.
CREATE OR ALTER VIEW dbo.vw_price_spread AS
-- One row per (code, price_type): the cross-hospital spread the "compare a procedure" screen shows.
SELECT
    c.code,
    c.code_type,
    d.example_description,
    c.price_type,
    c.n_hospitals,
    c.n_payers,
    c.n_prices,
    c.min_amount,
    c.median_amount,
    c.max_amount,
    CAST(CASE WHEN c.min_amount > 0 THEN c.max_amount / c.min_amount ELSE NULL END AS DECIMAL(10,1)) AS max_to_min_ratio,
    c.n_flagged,
    CAST(CASE WHEN c.n_prices > 0 THEN 100.0 * c.n_flagged / c.n_prices ELSE 0 END AS DECIMAL(6,2)) AS pct_flagged
FROM dbo.mart_price_comparison c
JOIN dbo.dim_procedure_code d ON d.code = c.code AND d.code_type = c.code_type;
GO

CREATE OR ALTER VIEW dbo.vw_hospital_quality AS
-- Dashboard "quality score next to the price" panel.
SELECT hospital_slug, hospital_name, state, quality_score, completeness, validity, consistency, freshness,
       days_since_last_update, total_prices, flagged_prices, pct_flagged,
       CASE WHEN quality_score >= 90 THEN 'good' WHEN quality_score >= 75 THEN 'fair' ELSE 'needs review' END AS quality_band
FROM dbo.mart_hospital_quality;
GO

CREATE OR ALTER VIEW dbo.vw_procedure_search AS
-- Typeahead: search procedures by description substring, ranked by how many hospitals publish it.
SELECT code, code_type, example_description, hospital_count, price_row_count
FROM dbo.dim_procedure_code;
GO
