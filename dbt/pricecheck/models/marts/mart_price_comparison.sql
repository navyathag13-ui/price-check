{{ config(materialized='table') }}
-- The dashboard/API's core query, precomputed: for each (code, price_type), the spread across hospitals and payers.
select
    f.code,
    f.code_type,
    any_value(f.description)                         as example_description,
    f.price_type,
    count(*)                                          as n_prices,
    count(distinct f.hospital_slug)                   as n_hospitals,
    count(distinct f.payer)                           as n_payers,
    min(f.amount)                                     as min_amount,
    round(median(f.amount), 2)                        as median_amount,
    max(f.amount)                                     as max_amount,
    round(stddev_pop(f.amount), 2)                    as stddev_amount,
    sum(case when f.is_flagged then 1 else 0 end)     as n_flagged
from {{ ref('fact_price') }} f
where f.code_type in ('CPT','HCPCS','MS-DRG')
group by f.code, f.code_type, f.price_type
having count(distinct f.hospital_slug) >= 2
