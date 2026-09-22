{{ config(materialized='table') }}
-- One row per (code, code_type) actually observed in current prices, with the number of hospitals publishing it.
select
    code,
    code_type,
    any_value(description)          as example_description,
    count(distinct hospital_slug)   as hospital_count,
    count(*)                        as price_row_count
from {{ ref('stg_price_current') }}
where code_type in ('CPT','HCPCS','MS-DRG','APR-DRG','ICD-10-PCS','NDC')
group by code, code_type
