# Price Check

A reproducible data-engineering pipeline for US hospital price-transparency files: ingest, validate against
versioned contracts, normalize into one canonical schema with full history (Delta Lake, SCD2), detect suspicious
prices, match procedures to standard codes across three methods, and serve price comparisons through a dbt gold
layer, a FastAPI + GraphQL API, and a Streamlit dashboard.

Every claim in this repo -- sizes, row counts, timings, precision/recall, cost -- comes from something that actually
ran on real data from 21 hospitals. Where something was not measured or not verified, that is stated plainly rather
than assumed. See `DECISIONS.md` for the architecture decision records (what was chosen, what was rejected, and the
evidence) and `docs/phaseN_report.md` for the generated, numbers-only reports behind each phase.

**Data findings, not medical or financial advice.** See the API/dashboard disclaimer.

## Problem statement

US hospitals must publish their prices, but the files are huge, inconsistent (tall CSV, wide CSV and JSON layouts), and full of bad values, so nobody can compare prices across hospitals. This project builds the pipeline that makes those files comparable: parse them into one schema with contract checks, keep full price history, flag suspicious prices, and match hospital procedure descriptions to standard codes. The goal was to measure each step's quality honestly instead of assuming it works.

## Results

Figures are quoted from the generated reports in `docs/` (each was produced by code in this repo on the real data; they were not re-run when this README was written).

| Area | Result | Source |
|---|---|---|
| Scale | 21 hospitals; 8.67 GB downloaded; 175,765,358 canonical rows parsed; **41,134,669 rows** in the Delta history table | `docs/phase3_report.md`, `docs/COST_REPORT.md` |
| Anomaly detection | On 54,000 injected corruptions (thresholds fixed beforehand): rules **81.3%** recall, isolation forest **23.2%**, combined **81.5%**. Weakest case: prices scaled x10 consistently across an item (19.8%). Precision was judged by an AI-labeled review of 103 flagged prices, **not** by a human expert. | `docs/phase4_report.md` |
| Procedure matching (200-item test set, top-1 accuracy) | rules+fuzzy 0.475, embedding search 0.57, LLM with candidates 0.515, LLM without candidates 0.12. Catch-all codes are hard: 0.0 / 0.227 / 0.152. The tiered strategy auto-resolved 85% of items at 66.5% precision on answered items, and sent the rest to human review. | `docs/phase5_report.md` |
| Spark vs DuckDB | DuckDB was faster than Spark at every size tested, from 986K to 164.5M rows (one MacBook Air; x2/x4 sizes are single runs on duplicated data). | `docs/phase6_report.md` |
| CI | Lint, tests, dbt build on real fixtures and `terraform validate` pass on GitHub Actions ([run](https://github.com/navyathag13-ui/price-check/actions/runs/35774815959)). | GitHub |
| Azure deployment | **Not deployed.** Terraform is written and validated, but `terraform apply` was never run. Cost figures in `docs/COST_REPORT.md` are estimates. | `docs/COST_REPORT.md` |

## How we got here

Built in nine phases, each ending with a generated numbers-only report and an architecture decision record in `DECISIONS.md` (24 in total): (1) source registry and polite downloader, (2) canonical model with versioned contracts and quarantine for bad rows, (3) Delta Lake SCD2 history, (4) anomaly detection, (5) procedure matching by three methods, (6) Spark vs DuckDB and storage experiments, (7) dbt gold layer, FastAPI + GraphQL API and Streamlit dashboard, (8) Terraform, CI and observability, (9) a streaming stretch goal. Several real bugs were found and fixed along the way (for example a data-loss bug in tall-CSV parsing and a missing directory in CI); the before/after evidence is in `docs/`.

## Status
All 9 phases complete, including the stretch goal (see DECISIONS.md for the full ADR list: 24 decision records). CI (lint, tests, dbt build against real fixtures, terraform validate) passes on GitHub Actions: https://github.com/navyathag13-ui/price-check/actions

## Quick start (local, no cloud)
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m pricecheck.ingest.download          # bronze: hash-addressed raw files, polite per-host downloader
python -m pricecheck.silver.make_contracts && python -m pricecheck.silver.pipeline   # silver: contract-validated canonical rows
python -m pricecheck.history.incremental       # Delta SCD2 history
cd dbt/pricecheck && dbt build                 # gold layer
streamlit run ../../dashboard/app.py           # dashboard
uvicorn pricecheck.serving.api:app --reload    # API (REST + /graphql)
```

See `DECISIONS.md`, `docs/`, and `dbt/README.md` for details on each phase.
