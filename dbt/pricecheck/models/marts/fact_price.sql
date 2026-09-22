{{ config(materialized='table') }}
-- Grain: one row per currently-active price fact. Anomaly flags joined in (left join: not every row is peer-scorable, see Phase 4).
select
    p.row_id,
    p.hospital_slug,
    p.code,
    p.code_type,
    p.description,
    p.setting,
    p.billing_class,
    p.payer,
    p.plan,
    p.price_type,
    p.amount,
    p.methodology,
    p.modifiers,
    p.effective_from,
    a.is_flagged,
    a.flag_peer_outlier,
    a.flag_negotiated_above_gross,
    a.flag_negotiated_outside_min_max,
    a.flag_cash_above_gross,
    a.flag_placeholder_value,
    a.flag_isolation_forest
from {{ ref('stg_price_current') }} p
left join {{ ref('stg_anomaly_flags') }} a on a.row_id = p.row_id
