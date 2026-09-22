"""Consolidate every phase's own per-run logs (already produced: bronze manifest, silver run_log, history ledger,
dbt run_results.json) into ONE queryable run-metrics table, rather than inventing a parallel logging system.

This is deliberately NOT a new source of truth -- it's a read model over logs that already exist and are already
each phase's own evidence (ADR-002, ADR-007, ADR-010). Re-running this after any pipeline stage keeps it current.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
from deltalake import write_deltalake

ROOT = Path(__file__).resolve().parents[3]
TABLE = ROOT / "data/delta/run_metrics"

SCHEMA = pa.schema([
    ("run_id", pa.string()), ("stage", pa.string()), ("slug", pa.string()), ("started_at", pa.string()),
    ("rows_in", pa.int64()), ("rows_out", pa.int64()), ("rows_rejected", pa.int64()), ("duration_s", pa.float64()),
    ("outcome", pa.string()), ("est_cost_usd", pa.float64()), ("detail", pa.string()),
])


def from_bronze() -> list[dict]:
    p = ROOT / "data/bronze/manifest.jsonl"
    if not p.exists():
        return []
    out = []
    for l in p.read_text().splitlines():
        r = json.loads(l)
        out.append({"run_id": f"bronze-{r['slug']}-{r.get('fetched_at','')}", "stage": "bronze_download", "slug": r["slug"],
                    "started_at": r.get("fetched_at", ""), "rows_in": 0, "rows_out": 0, "rows_rejected": 0,
                    "duration_s": float(r.get("duration_s") or 0), "outcome": r.get("outcome", "unknown"),
                    "est_cost_usd": 0.0, "detail": r.get("error", "")[:200] if r.get("error") else ""})
    return out


def from_silver() -> list[dict]:
    p = ROOT / "data/silver/run_log.jsonl"
    if not p.exists():
        return []
    out = []
    for l in p.read_text().splitlines():
        r = json.loads(l)
        out.append({"run_id": f"silver-{r['slug']}-{r['sha256'][:12]}", "stage": "silver_parse", "slug": r["slug"],
                    "started_at": r.get("at", ""), "rows_in": r["source_rows_in"], "rows_out": r["rows_out"],
                    "rows_rejected": r["rejects"], "duration_s": float(r["duration_s"]), "outcome": r["outcome"],
                    "est_cost_usd": 0.0, "detail": json.dumps(r.get("reject_reasons", {}))[:200]})
    return out


def from_history() -> list[dict]:
    from pricecheck.history.delta_store import ledger_records
    ledger_path = ROOT / "data/delta/ingestion_ledger"
    if not ledger_path.exists():
        return []
    out = []
    for r in ledger_records(ledger_path):
        out.append({"run_id": f"history-{r['slug']}-{r['source_sha256'][:12]}", "stage": "history_load", "slug": r["slug"],
                    "started_at": str(r["loaded_at"]), "rows_in": r["staged_rows"],
                    "rows_out": r["rows_inserted"] + r["rows_unchanged"], "rows_rejected": 0,
                    "duration_s": float(r["duration_s"]), "outcome": r["mode"], "est_cost_usd": 0.0,
                    "detail": f"closed={r['rows_closed']} synthetic={r['synthetic']}"})
    return out


def from_dbt() -> list[dict]:
    p = ROOT / "dbt/pricecheck/target/run_results.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text())
    out = []
    for r in d.get("results", []):
        out.append({"run_id": f"dbt-{r['unique_id']}-{d['metadata']['generated_at']}", "stage": "dbt_" + r["unique_id"].split(".")[0],
                    "slug": r["unique_id"].split(".")[-1], "started_at": d["metadata"]["generated_at"], "rows_in": 0, "rows_out": 0,
                    "rows_rejected": 0, "duration_s": float(r["execution_time"]), "outcome": r["status"],
                    "est_cost_usd": 0.0, "detail": (r.get("message") or "")[:200]})
    return out


def build() -> dict:
    rows = from_bronze() + from_silver() + from_history() + from_dbt()
    if not rows:
        return {"rows": 0, "note": "no per-stage logs found yet"}
    write_deltalake(str(TABLE), pa.Table.from_pylist(rows, schema=SCHEMA), mode="overwrite")
    by_stage: dict[str, int] = {}
    for r in rows:
        by_stage[r["stage"]] = by_stage.get(r["stage"], 0) + 1
    return {"rows": len(rows), "by_stage": by_stage, "built_at": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
