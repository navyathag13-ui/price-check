# What I re-checked (2026-09-23)

Machine: Apple M4 MacBook, macOS 26.5.1. These are spot checks I ran again while preparing this README; the full set of measurements is in the phase reports next to this file.

| Check | Result |
|---|---|
| Row count in the Delta history table (`data/delta/price_history`, version 20), queried with DuckDB | 41,134,669 rows, 21 distinct hospitals |
| Total size of downloaded files, summed from `data/bronze/manifest.jsonl` | 8,671,191,924 bytes (8.67 GB) over 23 manifest entries. The cost report says "21 hospital files"; the manifest has two more entries than that. |
| Local test suite (`pytest -q tests`) | 111 passed |
| `terraform validate` (Terraform 1.9.8, fresh init without a backend) | Configuration is valid |
| Terraform state file in the project | None. `terraform apply` was never run, so nothing is deployed. |
| GitHub Actions on the latest push | Success: https://github.com/navyathag13-ui/price-check/actions/runs/35917455577 |
| Secrets in git history | None found (the hex strings that turn up are record hashes in committed CSV fixtures) |

## Not re-run

- The 41M-row load itself, the anomaly evaluation, the matching evaluation and the Spark and DuckDB benchmarks. Their numbers come from the generated reports in this folder.
- Anything on Azure.
