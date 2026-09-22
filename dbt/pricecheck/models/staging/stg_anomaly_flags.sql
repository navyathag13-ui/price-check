-- Note: robust_z and amount are NOT persisted in flags.parquet (only the derived flag booleans and if_score are) --
-- join to stg_price_current on row_id if amount/robust_z are needed downstream.
select row_id, hospital_slug, code, price_type, if_score,
       R1_robust_z as flag_peer_outlier, R2_neg_gt_gross as flag_negotiated_above_gross,
       R3_out_of_range as flag_negotiated_outside_min_max, R4_cash_gt_gross as flag_cash_above_gross,
       R5_placeholder as flag_placeholder_value, IF_flag as flag_isolation_forest, any_flag as is_flagged
from {{ source('raw', 'raw_anomaly_flags') }}
