-- Every version (current and closed) of every price fact. Used for "what changed" lineage, not for current-state queries.
select
    row_id, key_hash, hospital_slug, code, code_type, description,
    coalesce(setting, 'unknown') as setting, coalesce(billing_class, 'unknown') as billing_class,
    payer, plan, price_type, cast(amount as decimal(14,4)) as amount, methodology, modifiers,
    first_source_sha256, effective_from, effective_to, is_current, closed_by_source_sha256, change_reason
from {{ source('raw', 'raw_price_history') }}
