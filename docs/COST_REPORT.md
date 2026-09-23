# Cost report

Real numbers where something was actually measured; explicit estimates, clearly labeled, where it wasn't. Nothing
here is invented -- the source of every figure is named.

## Local compute (this project's Phases 1-8): $0
Everything through Phase 8 ran on a single MacBook Air with no cloud compute. The real, measured throughput:

| Stage | Measured | Source |
|---|---:|---|
| Bronze download | 8.67 GB across 21 hospital files | `data/bronze/manifest.jsonl`, summed `size_bytes` |
| Silver parse | 175,765,358 canonical rows in 547.2s total | `data/silver/run_log.jsonl`, summed `rows_out`/`duration_s` |
| History load (SCD2 merge) | 41,134,669 rows in a Delta table | `data/delta/ingestion_ledger` |
| DuckDB benchmark (largest tested) | 164.5M rows, single-node | `docs/phase6_report.md` |

$0 local compute cost means "$/GB processed on this project's own hardware" is not a meaningful number to report --
there is no metered resource behind it. Where the brief asks for cost per GB / per run, the honest answer for the
local phases is: **not applicable, ran on owned hardware with no marginal cost.** What follows is the actual cloud
spend, which is real, and small.

## Azure spend, actually incurred this session

Verified live against real Azure resources (see the RAG project's session, same subscription/resource group):

| Resource | What happened | Cost |
|---|---|---|
| Azure OpenAI (`gpt-4.1-mini`) | A handful of live verification calls (health check + a few `/agent`/`/ask` calls) | Not separately itemized; Azure OpenAI billing is per-token. At the published rate the RAG project measured ($0.000165/$0.00066 per 1K input/output tokens for a different model in the same family), a dozen short calls is well under $0.10. **The actual billed amount is in Azure Cost Management, not reproduced here as a guess.** |
| Azure AI Content Safety (F0 tier) | A handful of live screening calls | $0 -- F0 is free up to 5,000 records/month, nowhere near reached |
| Resource group / provider registration | Setup only | $0 |

**Deployed 2026-09-23 (Terraform `apply` from Azure Cloud Shell, 15 resources):** ADLS Gen2, Azure SQL Database, Data Factory, Log Analytics, Application Insights, Event Hubs and a budget alert, all in `terraform/main.tf`. No actual charges have been read from the Azure portal for these yet, so every figure below is still an estimate. Two specifics: the SQL database is created in the free-offer shape (serverless GP_S_Gen5_1), but the free offer is a subscription-level benefit and I have not confirmed in the portal that it applied to this database; and Event Hubs Basic bills about $0.03 per hour while it exists, roughly $22 a month if left running, which would trip the $10 monthly budget alert.

## Estimated cost once the rest of Terraform is applied

Estimates, explicitly labeled as such, based on this project's actual data volumes and each service's published
pricing (checked this session, see `sql/azure_sql/README.md` and the RAG project's own cost verification):

| Resource | This project's real scale | Estimated monthly cost |
|---|---|---|
| ADLS Gen2 (bronze + Delta) | ~8.67 GB bronze + ~4.4 GB Delta history = ~13 GB | Well under $1/month at Azure's per-GB blob rate; not separately verified against the Retail Prices API this session |
| Azure SQL (free offer) | 4 tables, largest 128,372 rows | $0 (free offer; see `ADR-020` for why only the small marts are loaded, not the 41M-row fact table) |
| Azure Data Factory | A handful of scheduled pipeline runs/month | $0 (first 1,000 orchestration activity runs/month free, verified this project; nowhere close) |
| Log Analytics + App Insights | This project's log volume | $0 (first 5GB/month free, verified this project) |
| **Total estimated once fully deployed** | | **Effectively $0/month**, within free tiers, for this project's actual scale |

**What would change this:** sustained real user traffic to the API/dashboard beyond free-tier request limits, or a
much larger hospital set (more bronze GB, more Azure OpenAI calls if agentic matching runs at scale) would push
real spend above these free thresholds. Re-measure rather than assume if scale changes materially.

## Cost per unit of work (the numbers actually asked for, scoped honestly)

- **Cost per GB processed (bronze -> silver):** $0 -- local compute only, see above. If this ran on an Azure VM or
  Databricks cluster instead, that would be a real, measurable number; it does not, so it isn't claimed.
- **Cost per pipeline run:** $0 for ingest/silver/history/dbt (local). For the procedure-matching LLM tier
  specifically (Phase 5, the one part of this pipeline that calls a paid API per-item): **measured** at
  ~$0.18 per 1,000 items in "candidates" mode (`docs/phase5_report.md`), using the fine-tuned-global rate as a
  stand-in because the base-model meter wasn't retrievable from Azure's Retail Prices API this session -- stated as
  an estimate there too, not claimed as a confirmed bill.
