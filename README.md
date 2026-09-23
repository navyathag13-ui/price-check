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

## Highlights

- **41.1 million** price rows from **21 hospitals**, kept as a versioned Delta Lake history you can query as of any past load
- A full medallion pipeline (raw, validated, warehouse) with per-hospital data contracts, a quarantine for bad rows, and **111 passing tests** including property-based ones
- An anomaly detector that catches **81.3%** of 54,000 deliberately injected pricing errors
- Three ways of matching hospital descriptions to billing codes (fuzzy, embeddings, LLM), compared head to head on a labelled test set
- A Spark versus DuckDB benchmark up to **164.5 million rows**
- dbt star schema with 27 tests, a FastAPI + GraphQL API, and a Streamlit dashboard
- Terraform for six Azure services, validated and ready to apply from Azure Cloud Shell
- 24 written architecture decision records, and a green GitHub Actions pipeline


## Why I built this

Since 2021 US hospitals have had to publish what they charge. In practice that means huge files (some are gigabytes), in different layouts, with different column names, plus plenty of typos and placeholder values. Technically the prices are public. Practically, nobody can compare them. I wanted to find out what it takes to turn that mess into something you can trust and query, and to measure honestly how well each step works.

So this is a full pipeline, built in nine phases: download the files politely, check them against versioned contracts, load them into one clean schema with the full price history, flag prices that look wrong, match each hospital's own procedure descriptions to standard billing codes, and serve comparisons through an API and a dashboard.

## Tech stack

| Stage | What I used |
|---|---|
| Language and tooling | Python 3.11, pytest 9 with Hypothesis (property tests), ruff for linting |
| Ingest | `requests`, streaming parsers (`ijson` for JSON, chunked CSV reading), hash-addressed raw files ("bronze") |
| Cleaning and contracts | Pydantic, one versioned YAML contract per hospital, a quarantine for rows that fail validation ("silver") |
| Storage and history | Parquet with Apache Arrow, Delta Lake (`deltalake` 1.6) with slowly-changing-dimension history and time-travel reports |
| Query engines | DuckDB 1.5 as the main engine, PySpark 4.2 for the comparison benchmark |
| Warehouse layer | dbt-core 1.12 with dbt-duckdb, a star schema, 27 dbt tests ("gold") |
| Anomaly detection | Rule checks plus scikit-learn IsolationForest |
| Procedure matching | rapidfuzz (fuzzy), sentence-transformers with FAISS (embeddings), Azure OpenAI `gpt-4.1-mini` (LLM) |
| Serving | FastAPI with Strawberry GraphQL, Streamlit dashboard, T-SQL views for Azure SQL |
| Cloud (written, not deployed) | Terraform with the `azurerm` 4.x provider: Data Lake Gen2, Azure SQL, Data Factory, Log Analytics, Application Insights, Event Hubs, a budget alert |
| Streaming (stretch goal) | Spark Structured Streaming on file-change events |
| CI | GitHub Actions: ruff, pytest, dbt build against committed fixtures, `terraform validate` |

## What came out

The numbers below come from the reports in `docs/`, which the code in this repo generated from the real files. I also re-checked a few of them on 2026-09-23 (see [`docs/VERIFICATION.md`](docs/VERIFICATION.md)).

**Scale.** 21 hospitals, 8.67 GB of downloaded files, 175,765,358 parsed rows, and **41,134,669 rows** in the final Delta history table (I re-counted this directly and it matched).

**Finding bad prices.** I injected 54,000 fake errors into real rows (prices multiplied by 10 or 100, divided by 10 or 100, placeholders like 999999.99, and so on) with the thresholds fixed beforehand. The rule checks caught **81.3%**, the isolation forest caught **23.2%**, and the two combined caught 81.5%. The weak spot is a price that is scaled by 10 across a whole item consistently, which is only caught 19.8% of the time. For precision I had an AI-assisted review of 103 flagged prices, and I want to be clear that this was not a review by a billing expert.

**Matching descriptions to codes.** On a 200-item test set: fuzzy matching got 47.5% of the top answers right, embedding search 57%, and the LLM (given candidates) 51.5%. The LLM without candidates got just 12%, because it cannot reliably remember exact billing codes. "Catch-all" codes were the hardest of all. The final strategy answers automatically on 85% of items with 66.5% precision on those, and sends the rest to a person.

**DuckDB versus Spark.** DuckDB was faster than Spark at every size I tried, from about 1 million to 164.5 million rows, on one MacBook Air. The gap closes as the data gets close to DuckDB's memory limit. (The two largest sizes are single runs on duplicated data, so treat them as indicative.)

**Tests and CI.** 111 tests pass locally. GitHub Actions passes ([latest run](https://github.com/navyathag13-ui/price-check/actions/runs/35917455577)). One caveat worth knowing: the multi-gigabyte raw data isn't in the repo, so in CI the tests that need it skip themselves and dbt runs against small committed fixtures. A green CI run therefore means the code and the contracts are healthy, not that the full 41 million row pipeline was re-run.

**Cloud.** The Terraform is written and `terraform validate` passes, but I never ran `terraform apply`, so nothing here is deployed to Azure. The cost numbers in `docs/COST_REPORT.md` are estimates.

## How it came together

Each phase ended with a generated report of numbers and a short decision record in `DECISIONS.md` (24 in total) covering what I picked, what I rejected and why.

1. Source registry and a polite, hash-addressed downloader
2. A canonical data model, contracts, and a quarantine for bad rows
3. Delta Lake history with time travel
4. Anomaly detection
5. Matching descriptions to codes, three ways
6. Spark versus DuckDB and storage experiments
7. dbt warehouse layer, API and dashboard
8. Terraform, CI and monitoring
9. A streaming stretch goal

I found real bugs along the way and kept the before-and-after evidence. The best example: while checking my deduplication step I noticed that generic prices were being lost when reading the tall CSV layout, so I fixed the parser and saved the before and after logs (`docs/phase3_dedupe_fix_*.log`). Another bug only showed up in CI, where a data folder I had assumed existed did not.

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
