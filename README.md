# Price Check

A reproducible data-engineering pipeline for US hospital price-transparency files: ingest, validate against
versioned contracts, normalize into one canonical schema with full history (Delta Lake, SCD2), detect suspicious
prices, match procedures to standard codes across three methods, and serve price comparisons through a dbt gold
layer, a FastAPI + GraphQL API, and a Streamlit dashboard.

Every claim in this repo -- sizes, row counts, timings, precision/recall, cost -- comes from something that actually
ran on real data from 21 hospitals, and each figure points to the report that produced it. See `DECISIONS.md` for the architecture decision records (what was chosen, what was rejected, and the
evidence) and `docs/phaseN_report.md` for the generated, numbers-only reports behind each phase.

**Data findings, not medical or financial advice.** See the API/dashboard disclaimer.

## Highlights

- **41.1 million** price rows from **21 hospitals**, kept as a versioned Delta Lake history you can query as of any past load
- A full medallion pipeline (raw, validated, warehouse) with per-hospital data contracts, a quarantine for bad rows, and **111 passing tests** including property-based ones
- An anomaly detector that catches **81.3%** of 54,000 deliberately injected pricing errors
- Three ways of matching hospital descriptions to billing codes (fuzzy, embeddings, LLM), compared head to head on a labelled test set
- A Spark versus DuckDB benchmark up to **164.5 million rows**
- dbt star schema with 27 tests, a FastAPI + GraphQL API, and a Streamlit dashboard
- Terraform for six Azure services, **applied to a real Azure subscription** (15 resources, 2026-09-23), with the serving tables loaded into Azure SQL (about 128,000 rows in the largest)
- 24 written architecture decision records, and a green GitHub Actions pipeline


## Why I built this

Since 2021 US hospitals have had to publish what they charge. In practice that means huge files (some are gigabytes), in different layouts, with different column names, plus plenty of typos and placeholder values. Technically the prices are public. Practically, nobody can compare them. I wanted to find out what it takes to turn that mess into something you can trust and query, and to measure how well each step works.

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
| Cloud (deployed with Terraform) | Terraform with the `azurerm` 4.x provider: Data Lake Gen2, Azure SQL, Data Factory, Log Analytics, Application Insights, Event Hubs, a budget alert |
| Streaming (stretch goal) | Spark Structured Streaming on file-change events |
| CI | GitHub Actions: ruff, pytest, dbt build against committed fixtures, `terraform validate` |

## What came out

The numbers below come from the reports in `docs/`, which the code in this repo generated from the real files. I also re-checked a few of them on 2026-09-23 (see [`docs/VERIFICATION.md`](docs/VERIFICATION.md)).

**Scale.** 21 hospitals, 8.67 GB of downloaded files, 175,765,358 parsed rows, and **41,134,669 rows** in the final Delta history table (I re-counted this directly and it matched).

**Finding bad prices.** I injected 54,000 fake errors into real rows (prices multiplied by 10 or 100, divided by 10 or 100, placeholders like 999999.99, and so on) with the thresholds fixed beforehand. The rule checks caught **81.3%**, the isolation forest caught **23.2%**, and the two combined caught **81.5%**. Prices scaled up by 10 or 100, placeholder values, and negotiated prices far above the gross charge are caught 95.9% to 100% of the time. The hardest case is a price scaled by 10 consistently across a whole item (19.8%), which is where the next detector would go. Precision was assessed with an AI-assisted review of 103 flagged prices; a review by a billing specialist is the natural next step.

**Matching descriptions to codes.** On a 200-item test set, fuzzy matching got 47.5% of the top answers right, embedding search 57%, and the LLM 51.5% when given a candidate list. Giving the LLM candidates is what makes it work: without them it gets 12%, because exact billing codes are hard to recall from memory. "Catch-all" codes were the hardest category for every method, which is why the final strategy is tiered: it answers automatically on 85% of items (66.5% precision on those) and sends the remaining 15% to a person for review.

**DuckDB versus Spark.** DuckDB was faster than Spark at every size I tried, from about 1 million to 164.5 million rows, on one MacBook Air, and the gap narrows as the data approaches DuckDB's memory limit. (The two largest sizes are single runs on duplicated data, so treat them as indicative.)

**Tests and CI.** 111 tests pass locally, and GitHub Actions passes ([latest run](https://github.com/navyathag13-ui/price-check/actions/runs/35917455577)). CI runs lint, the tests that don't need the multi-gigabyte raw files, `dbt build` against committed fixtures, and `terraform validate`; the data-dependent tests run on the full dataset locally.

**Cloud.** On 2026-09-23 I ran `terraform apply` from Azure Cloud Shell (`terraform/cloudshell_deploy.sh`) and it created all 15 resources in my subscription's `rg-pricecheck` group: a Data Lake Gen2 storage account with `bronze` and `delta` containers, an Azure SQL server and database, Data Factory, Log Analytics, Application Insights, an Event Hubs namespace with a hub and two access rules, and a monthly budget alert. I then loaded the four gold summary tables into the Azure SQL database (21, 79,213, 128,372 and 21 rows), and the T-SQL view returned 128,372 rows live from Azure. The full pipeline and the 41-million-row history run locally, and the small serving tables live in Azure SQL. Next up: uploading the Delta history to the storage account and scheduling daily loads with Data Factory. Along the way I found that this subscription restricts new SQL servers in `northcentralus`, so the SQL server lives in `westus` (a separate `sql_location` variable). Cost estimates are in `docs/COST_REPORT.md`.

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
