# dbt gold layer

Reads the Phase 3/4 Delta tables (price_history, quality_scores) and the Phase 4 anomaly flags parquet directly via
DuckDB's native readers (`delta_scan`, `read_parquet`), wired up in `on-run-start` hooks in `dbt_project.yml` — no
copy step, no separate ETL into dbt's own storage.

## Layout
- `models/staging/` — 1:1 renaming/casting views over the sources (`stg_price_current`, `stg_price_history`,
  `stg_quality_scores`, `stg_anomaly_flags`, `stg_hospitals`).
- `models/marts/` — the gold star schema: `dim_hospital`, `dim_procedure_code`, `fact_price` (grain: one row per
  currently-active price fact, joined with its anomaly flags), plus two precomputed marts the API/dashboard read
  directly: `mart_price_comparison` (price spread per code across hospitals) and `mart_hospital_quality`.
- `tests/` — 3 singular tests, plus schema tests (`unique`, `not_null`, `relationships`, `accepted_values`,
  `dbt_utils.accepted_range`, `dbt_utils.unique_combination_of_columns`) in each `schema.yml`.

## Real result of `dbt build` on the full 41.1M-row table (2026-09-21)
**41 passed, 1 warning, 0 errors, 0 skips.** The one warning (`assert_min_amount_le_max_amount`, 383,304 rows) is a
known real data-quality issue documented in `DECISIONS.md` ADR-014 (`m_min_gt_max_rate`) — some hospitals publish a
`min` price above their own `max` price for the same item. It's configured `severity: warn`, not silenced, because
it's evidence about the source data, not a pipeline bug.

## Run it
```bash
cd dbt/pricecheck
export DBT_PROFILES_DIR="$(pwd)/../profiles"
export DBT_DUCKDB_PATH="$(pwd)/../../data/gold/pricecheck.duckdb"
export PRICE_HISTORY_PATH="$(pwd)/../../data/delta/price_history"
export QUALITY_SCORES_PATH="$(pwd)/../../data/delta/quality_scores"
export ANOMALY_FLAGS_PATH="$(pwd)/../../data/anomaly/flags.parquet"
export HOSPITAL_REGISTRY_PATH="$(pwd)/../../data/dbt_sources/hospitals.csv"
python ../../scripts/export_hospital_registry.py   # config/hospitals.yaml -> data/dbt_sources/hospitals.csv
dbt deps && dbt build
dbt docs generate && dbt docs serve   # lineage graph in the browser
```
