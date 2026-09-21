"""A pinned, reproducible report: negotiated/cash price spread per procedure code across hospitals.

Reproducibility contract: the report is a pure function of (params, Delta table version). The run is recorded in
`reports/ledger.jsonl` with the table version and the SHA-256 of the exact CSV bytes; `reproduce()` re-reads that
version via Delta time travel and must produce byte-identical output.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from deltalake import DeltaTable

ROOT = Path(__file__).resolve().parents[3]
HEADER = ["code", "code_type", "price_type", "hospitals", "prices", "min", "median", "max"]


def _scan(table: Path, version: int | None) -> str:
    return f"delta_scan('{table}'" + (f", version={version}" if version is not None else "") + ")"


def run_report(table: Path, params: dict, version: int | None = None, as_of_ts: datetime | None = None) -> tuple[bytes, dict]:
    dt = DeltaTable(str(table), version=version) if version is not None else DeltaTable(str(table))
    con = duckdb.connect()
    con.execute("INSTALL delta; LOAD delta;")
    if as_of_ts is not None:      # SCD2 point-in-time on the table as it is *now*
        ts = as_of_ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f+00")
        where = f"effective_from <= timestamptz '{ts}' AND (effective_to IS NULL OR effective_to > timestamptz '{ts}')"
    else:                          # the state at that Delta version
        where = "is_current"
    codes = ", ".join("'" + c.replace("'", "''") + "'" for c in params["codes"])
    types = ", ".join("'" + t + "'" for t in params["price_types"])
    rows = con.execute(f"""
        SELECT code, code_type, price_type, count(DISTINCT hospital_slug) AS hospitals, count(*) AS prices,
               min(amount) AS mn, quantile_cont(cast(amount as double), 0.5) AS med, max(amount) AS mx
        FROM {_scan(table, version)} WHERE {where} AND code IN ({codes}) AND price_type IN ({types})
        GROUP BY code, code_type, price_type ORDER BY code, code_type, price_type""").fetchall()
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    for c, ct, pt, nh, n, mn, med, mx in rows:
        w.writerow([c, ct, pt, nh, n, f"{mn:.4f}", f"{med:.4f}", f"{mx:.4f}"])
    data = buf.getvalue().encode()
    return data, {"history_version": dt.version(), "rows": len(rows), "output_sha256": hashlib.sha256(data).hexdigest()}


def record(table: Path, params: dict, ledger: Path, version: int | None = None) -> dict:
    data, meta = run_report(table, params, version)
    run_id = uuid.uuid4().hex[:12]
    out = ledger.parent / "outputs" / f"{run_id}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    rec = {"run_id": run_id, "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "table": str(table),
           "params": params, "params_sha256": hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest(), **meta}
    with ledger.open("a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def reproduce(run_id: str, ledger: Path) -> dict:
    rec = next(r for r in map(json.loads, ledger.read_text().splitlines()) if r["run_id"] == run_id)
    data, meta = run_report(Path(rec["table"]), rec["params"], rec["history_version"])
    return {"run_id": run_id, "recorded_sha256": rec["output_sha256"], "reproduced_sha256": meta["output_sha256"],
            "history_version": rec["history_version"], "identical": meta["output_sha256"] == rec["output_sha256"]}
