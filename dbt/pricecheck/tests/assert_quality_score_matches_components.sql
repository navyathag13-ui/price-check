-- The quality_score column must actually equal the documented formula (ADR-014): equal-weight mean of the 4 components x 100.
-- Catches drift between quality/scores.py's Python formula and what's actually landed in the Delta table.
select hospital_slug, quality_score, completeness, validity, consistency, freshness,
       round((completeness + validity + consistency + freshness) / 4 * 100, 1) as recomputed
from {{ ref('stg_quality_scores') }}
where abs(quality_score - round((completeness + validity + consistency + freshness) / 4 * 100, 1)) > 0.1
