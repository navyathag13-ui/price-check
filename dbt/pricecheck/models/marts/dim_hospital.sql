{{ config(materialized='table') }}
-- One row per hospital, joined with its latest quality score.
with latest_quality as (
    select *, row_number() over (partition by hospital_slug order by as_of desc) as rn
    from {{ ref('stg_quality_scores') }}
)
select
    h.hospital_slug,
    h.hospital_name,
    h.state,
    h.hospital_group,
    q.as_of              as quality_as_of,
    q.quality_score,
    q.completeness,
    q.validity,
    q.consistency,
    q.freshness,
    q.m_days_since_update as days_since_last_update
from {{ ref('stg_hospitals') }} h
left join latest_quality q on q.hospital_slug = h.hospital_slug and q.rn = 1
