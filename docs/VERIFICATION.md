# What I re-checked (2026-09-23)

Machine: Apple M4 MacBook, macOS 26.5.1. These are spot checks I ran again while preparing this README; the full set of measurements is in the phase reports next to this file.

| Check | Result |
|---|---|
| Row count in the Delta history table (`data/delta/price_history`, version 20), queried with DuckDB | 41,134,669 rows, 21 distinct hospitals |
| Total size of downloaded files, summed from `data/bronze/manifest.jsonl` | 8,671,191,924 bytes (8.67 GB) over 23 manifest entries. The cost report says "21 hospital files"; the manifest has two more entries than that. |
| Local test suite (`pytest -q tests`) | 111 passed |
| `terraform validate` (Terraform 1.9.8, fresh init without a backend) | Configuration is valid |
| Terraform state file in the local project | None. The apply was run from Azure Cloud Shell instead (next section), so no state file exists on this laptop. |
| GitHub Actions on the latest push | Success: https://github.com/navyathag13-ui/price-check/actions/runs/35917455577 |
| Secrets in git history | None found (the hex strings that turn up are record hashes in committed CSV fixtures) |

## Numbers quoted from the phase reports

- The 41M-row load, the anomaly evaluation, the matching evaluation and the Spark and DuckDB benchmarks are quoted from the generated reports in this folder, each produced by code in this repo.

## Azure deployment (2026-09-23)

I ran `terraform/cloudshell_deploy.sh` in Azure Cloud Shell (my laptop cannot sign in to this tenant). Evidence is the Cloud Shell output: a first apply created 11 resources and then failed on the SQL server (`ProvisioningDisabled` in `northcentralus`); after moving the SQL server to `westus` and deleting the stub the failed attempt left behind, `Apply complete! Resources: 4 added, 0 changed, 0 destroyed`. The outputs listed in `terraform/README.md` came from that run. That output is the evidence; the tenant blocks the Azure CLI from my laptop, so Cloud Shell is where Azure gets queried.

### Data loaded into Azure SQL

`python -m pricecheck.serving.load_azure_sql` from my laptop, against the deployed database, printed:

```
dim_hospital                       21 rows  0.8s
dim_procedure_code             79,213 rows  29.5s
mart_price_comparison         128,372 rows  82.4s
mart_hospital_quality              21 rows  0.4s
vw_price_spread row count (verified live): 128372
```

Before this worked I fixed three schema mistakes and made the loader batch its inserts (500 rows per request; the first version sent one row per network round trip and would have taken hours). I tested both fixes against a local SQL Server in Docker first, where the column totals matched the source DuckDB file exactly. On the Azure database itself I have only the loader's own row counts, not a column-by-column comparison.

Next checks: confirm in the portal that the SQL free offer applied to the database, read the actual cost so far, and start using the storage account, Data Factory and Event Hubs.
