-- Every flagged row in the anomaly table must correspond to a real current price fact (no dangling row_ids).
select a.row_id
from {{ ref('stg_anomaly_flags') }} a
left join {{ ref('stg_price_current') }} p on p.row_id = a.row_id
where p.row_id is null
