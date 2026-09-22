-- Current (is_current) price facts only, light renaming/casting. Grain: one row per price fact version currently active.
select
    row_id,
    key_hash,
    hospital_slug,
    code,
    code_type,
    description,
    coalesce(setting, 'unknown')       as setting,
    coalesce(billing_class, 'unknown') as billing_class,
    payer,
    plan,
    price_type,
    cast(amount as decimal(14,4))      as amount,
    methodology,
    modifiers,
    first_source_sha256,
    effective_from
from {{ source('raw', 'raw_price_history') }}
where is_current
