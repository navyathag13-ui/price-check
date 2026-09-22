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

## Status
Phases 1-7 of 9 complete (see DECISIONS.md for the full list). In progress: Terraform, CI/CD, orchestration,
observability, runbook, cost report (Phase 8), stretch streaming (Phase 9).

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
