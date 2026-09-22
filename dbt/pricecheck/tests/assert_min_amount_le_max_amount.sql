-- Known real data issue (see DECISIONS.md ADR-014 m_min_gt_max_rate): some hospitals publish min > max on the same
-- item. Kept as a WARN (not a hard failure) because it documents real upstream hospital data, not a pipeline bug --
-- this test's row count is exactly the evidence a "consistency" component of the quality score is built from.
{{ config(severity='warn') }}
with mn as (select hospital_slug, code, description, setting, billing_class, amount as mn from {{ ref('fact_price') }} where price_type = 'min'),
     mx as (select hospital_slug, code, description, setting, billing_class, amount as mx from {{ ref('fact_price') }} where price_type = 'max')
select mn.hospital_slug, mn.code, mn.mn, mx.mx
from mn join mx using (hospital_slug, code, description, setting, billing_class)
where mn.mn > mx.mx
