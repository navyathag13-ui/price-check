select hospital_slug, source_sha256, as_of, items, price_rows, completeness, validity, consistency, freshness, quality_score,
       m_reject_rate, m_sentinel_rate, m_standard_code_share, m_days_since_update, m_template_current
from {{ source('raw', 'raw_quality_scores') }}
