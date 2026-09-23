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

## Not re-run

- The 41M-row load itself, the anomaly evaluation, the matching evaluation and the Spark and DuckDB benchmarks. Their numbers come from the generated reports in this folder.

## Azure deployment (2026-09-23)

I ran `terraform/cloudshell_deploy.sh` in Azure Cloud Shell (my laptop cannot sign in to this tenant). Evidence is the Cloud Shell output: a first apply created 11 resources and then failed on the SQL server (`ProvisioningDisabled` in `northcentralus`); after moving the SQL server to `westus` and deleting the stub the failed attempt left behind, `Apply complete! Resources: 4 added, 0 changed, 0 destroyed`. The outputs listed in `terraform/README.md` came from that run. I read that output; I have not independently queried Azure from this machine, since the tenant blocks the Azure CLI here.

Not verified: that the SQL free offer applied to the database (check the database's page in the portal), the actual cost so far, and any use of the deployed resources (nothing has been loaded into them).
