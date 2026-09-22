{{ config(materialized='table') }}
-- Per-hospital summary joining quality score with observed anomaly-flag rate, for the dashboard.
select
    d.hospital_slug,
    d.hospital_name,
    d.state,
    d.quality_score,
    d.completeness,
    d.validity,
    d.consistency,
    d.freshness,
    d.days_since_last_update,
    count(f.row_id)                                        as total_prices,
    sum(case when f.is_flagged then 1 else 0 end)           as flagged_prices,
    round(100.0 * sum(case when f.is_flagged then 1 else 0 end) / nullif(count(f.row_id), 0), 2) as pct_flagged
from {{ ref('dim_hospital') }} d
left join {{ ref('fact_price') }} f on f.hospital_slug = d.hospital_slug
group by d.hospital_slug, d.hospital_name, d.state, d.quality_score, d.completeness, d.validity, d.consistency, d.freshness, d.days_since_last_update
