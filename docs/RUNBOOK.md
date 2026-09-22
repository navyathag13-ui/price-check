# Runbook

What breaks in this pipeline, how you find out, and how you fix it. Written from what actually happened building
this project (real errors this session, not hypothetical ones), plus the genuine failure modes each phase's own
ADR already documented.

## How you find out something broke

Today (no live cloud alerting wired up -- see "What's not wired up" at the bottom):
```bash
python -m pricecheck.observability.alerts        # shrink / disappearance / shape-change / staleness
python -m pricecheck.observability.run_metrics    # consolidated run history across every stage
cat data/bronze/alerts.jsonl 2>/dev/null | tail   # contract violations + warnings (Phase 2)
```
Once Terraform is applied (`terraform/README.md`): the budget alert emails at 50/80/100% of the monthly threshold,
and Application Insights receives request/exception telemetry if the serving API is deployed with
`APPLICATIONINSIGHTS_CONNECTION_STRING` set (same pattern used in the earlier RAG project).

## Real incidents from building this project, and the actual fix

| What happened | How it showed up | Fix |
|---|---|---|
| A 2.88GB hospital download (Atrium) failed mid-transfer with a broken pipe | Manifest entry: `outcome: failed`, `error: ChunkedEncodingError` | Re-ran `python -m pricecheck.ingest.download --slug atrium-cmc --skip-existing`; the downloader's own retry (3 attempts, backoff) didn't cover this particular failure mode, a plain re-run did. If it happens again repeatedly, that's exactly what the new `repeated_failure` alert (3+ consecutive) is for. |
| Three JSON files (Stanford, UCSF, UChicago) failed to profile | `ijson.common.IncompleteJSONError: lexical error: invalid char` | UTF-8 BOM at the start of the file, which the streaming JSON parser rejects. Fixed in `ingest/profile.py` and `silver/parsers.py` to strip a leading BOM; regression tests added. |
| Silently dropped real price data | Nothing errored -- found by re-reading raw file bytes during Phase 3 investigation, not by any test failing | A tall-CSV parser bug deduplicated "generic" prices (gross/cash/min/max) per *consecutive item*, but one HCPCS drug code can legitimately carry different gross prices across adjacent rows (one per NDC). Recovered 76,778 price facts after the fix. **Lesson: "no errors" is not the same as "correct" -- this is why every phase's report script recomputes real counts from the actual data rather than trusting a clean run.** |
| `dbt build` failed with a missing `amount` column | `Binder Error: Referenced column "amount" not found` | The anomaly flags parquet (Phase 4) never persisted `amount`/`robust_z`, only the boolean flags + `if_score`. The dbt staging model assumed a wider schema than the file actually has. Fixed the model to match reality, not the other way around. |
| CI's `dbt-tests` job failed on the very first real run | GitHub Actions log: `IO Error: Cannot open file ".../data/gold/pricecheck_ci.duckdb": No such file or directory` | `data/gold/` only existed locally because earlier manual runs had created it. Fixed with `mkdir -p data/gold` in the workflow. **Lesson: "it works on my machine" is not verification -- this project tests against a genuinely fresh clone before trusting anything in CI.** |
| A repo push failed with HTTP 408 | `git push` timed out | The Phase 4 commit had accidentally included 1.1GB of regeneratable anomaly-detection parquet/joblib files. Caught before anything landed on GitHub (`git ls-remote` showed the remote was still empty); rewrote history with `git filter-repo` rather than just gitignoring going forward. |
| Azure CLI / Terraform apply can't authenticate from this machine | `AADSTS...` Conditional Access error, or `az login` hangs | The university tenant blocks non-interactive CLI/SDK auth from outside the portal/Cloud Shell. Not fixable from here -- run the equivalent commands in Azure Cloud Shell instead (every `deploy`/`sql/azure_sql`/`terraform` README in this repo gives the exact commands). |

## Common operational failures, by phase (what to check first)

- **A hospital's file 404s or the URL in `config/hospitals.yaml` is stale.** Hospitals move their MRF URLs without
  notice (CMS only requires the `/cms-hpt.txt` index to stay current, not the file URL itself). Re-fetch that
  hospital's `cms-hpt.txt` and update the registry entry; this is a real, expected occurrence, not a bug.
- **A file's reject rate exceeds its contract's `max_reject_rate` and gets quarantined.** Check
  `data/quarantine/<slug>/<sha>.json` for the reasons, then `data/bronze/alerts.jsonl` for the alert. Usually means
  the hospital changed its column layout; update `contracts/<slug>.v1.yaml` deliberately (bump `contract_version`)
  rather than loosening `max_reject_rate` to make the alarm go away.
- **History load reports `mode: noop` when you expected `merge`.** The new file's content hash differs but its
  *data* is identical to what's already loaded (e.g. the hospital re-published with a cosmetic change). This is
  correct, idempotent behavior, not a bug -- check `data/delta/ingestion_ledger` to confirm.
- **`dbt build` fails on a schema test.** Read the failure before loosening the test. Some failures are real data
  issues that are *supposed* to surface (see `assert_min_amount_le_max_amount`, deliberately a WARN not an ERROR,
  because it's evidence about the source data, not a pipeline bug) -- decide per-case, don't blanket-suppress.
- **The API/dashboard shows stale prices.** Check `mart_hospital_quality.days_since_last_update` and
  `observability.alerts`' `stale` findings; re-run the pipeline for that hospital.

## Backfill / reprocessing

Everything is idempotent by content hash (ADR-002, ADR-010) -- re-running any stage for already-processed data is
always safe and cheap (it detects "already done" and skips). To force a full reprocess of one hospital end to end:
```bash
python -m pricecheck.ingest.download --slug <slug>
python -m pricecheck.silver.pipeline --slug <slug> --force
python -m pricecheck.history.incremental --slug <slug>
cd dbt/pricecheck && dbt build --select +fact_price+
```
To reproduce a past report exactly, see `scripts/prove_reproducibility.py` and `pricecheck.reports.median_price.reproduce()`.

## What's not wired up yet (stated plainly, not hidden)
- No live paging/on-call -- alerts are a script you run, not a push notification. Wiring `observability.alerts`
  into an Azure Function on a Data Factory schedule, emailing via Action Group, is the natural next step once ADF
  exists (see `terraform/main.tf`).
- `run_metrics` has an `est_cost_usd` column that is currently always 0.0 for local stages (they have no cloud
  cost) -- it is not yet populated for the Azure OpenAI/Content Safety calls made in the RAG project's session;
  real cost tracking would pull from Azure Cost Management's API, not this repo's own logs.
