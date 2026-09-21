"""Delta Lake SCD-Type-2 price history + ingestion ledger (delta-rs; no Spark needed at this scale)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from deltalake import DeltaTable, write_deltalake

TS = pa.timestamp("us", tz="UTC")
HISTORY_SCHEMA = pa.schema([
    ("row_id", pa.string()), ("key_hash", pa.string()), ("hospital_slug", pa.string()), ("description", pa.string()),
    ("code", pa.string()), ("code_type", pa.string()), ("alt_codes", pa.string()), ("setting", pa.string()),
    ("billing_class", pa.string()), ("payer", pa.string()), ("plan", pa.string()), ("price_type", pa.string()),
    ("dup_seq", pa.int32()), ("amount", pa.decimal128(14, 4)), ("methodology", pa.string()), ("modifiers", pa.string()),
    ("row_hash", pa.string()), ("first_source_sha256", pa.string()), ("effective_from", TS), ("effective_to", TS),
    ("is_current", pa.bool_()), ("closed_by_source_sha256", pa.string()), ("change_reason", pa.string()),
])
LEDGER_SCHEMA = pa.schema([
    ("slug", pa.string()), ("source_sha256", pa.string()), ("loaded_at", TS), ("mode", pa.string()),
    ("staged_rows", pa.int64()), ("rows_inserted", pa.int64()), ("rows_closed", pa.int64()),
    ("rows_unchanged", pa.int64()), ("history_version_after", pa.int64()), ("duration_s", pa.float64()),
    ("synthetic", pa.bool_()),
])
COLS = [f.name for f in HISTORY_SCHEMA]


def _ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f+00")


def duck() -> "duckdb.DuckDBPyConnection":
    """DuckDB with its native Delta reader. Used instead of registering a delta-rs pyarrow dataset because MERGE
    output files use Arrow string_view, which DuckDB's filter pushdown over a pyarrow dataset cannot compare."""
    con = duckdb.connect()
    con.execute("INSTALL delta; LOAD delta;")
    return con


def has_rows(path: Path, slug: str) -> bool:
    if not DeltaTable.is_deltatable(str(path)):
        return False
    return duck().execute(f"SELECT count(*) FROM delta_scan('{path}') WHERE hospital_slug = '{slug}'").fetchone()[0] > 0


def initial_load(path: Path, staged: Path, sha: str, now: datetime, tmp: Path) -> dict:
    """First time a hospital is seen: plain append of its snapshot as 'current' rows."""
    tmp.mkdir(parents=True, exist_ok=True)
    out = tmp / f"initial_{sha[:12]}.parquet"
    con = duckdb.connect()
    con.execute(f"SET temp_directory='{tmp}'; SET preserve_insertion_order=false")
    con.execute(f"""COPY (SELECT md5(key_hash || '|{sha}') AS row_id, key_hash, hospital_slug, description, code, code_type,
        alt_codes, setting, billing_class, payer, plan, price_type, dup_seq, cast(amount as decimal(14,4)) AS amount,
        methodology, modifiers, row_hash, '{sha}' AS first_source_sha256, timestamptz '{_ts(now)}' AS effective_from,
        cast(NULL as timestamptz) AS effective_to, true AS is_current, cast(NULL as varchar) AS closed_by_source_sha256,
        cast(NULL as varchar) AS change_reason FROM read_parquet('{staged}')) TO '{out}' (FORMAT parquet, COMPRESSION zstd)""")
    con.close()
    pf = pq.ParquetFile(out)
    reader = pa.RecordBatchReader.from_batches(HISTORY_SCHEMA, (b.cast(HISTORY_SCHEMA) for b in pf.iter_batches(200_000)))
    write_deltalake(str(path), reader, mode="append", partition_by=["hospital_slug"])
    n = pf.metadata.num_rows
    out.unlink()
    return {"mode": "initial", "rows_inserted": n, "rows_closed": 0, "rows_unchanged": 0}


def apply_version(path: Path, slug: str, staged: Path, sha: str, now: datetime, tmp: Path) -> dict:
    """SCD2 MERGE for a new snapshot of a known hospital. Snapshot semantics: the file is the whole price list,
    so a current row absent from it is closed ('removed'), a row whose attributes differ is closed ('changed')
    and replaced, and unseen keys are inserted. Only changed rows are touched."""
    dt = DeltaTable(str(path))
    con = duck()
    con.execute(f"SET temp_directory='{tmp}'; SET preserve_insertion_order=false")
    con.execute(f"CREATE VIEW cur AS SELECT * FROM delta_scan('{path}') WHERE hospital_slug = '{slug}' AND is_current")
    con.execute(f"CREATE VIEW stg AS SELECT * FROM read_parquet('{staged}')")
    ts = f"timestamptz '{_ts(now)}'"
    new_cols = ", ".join(f"s.{c}" for c in ("key_hash", "hospital_slug", "description", "code", "code_type", "alt_codes", "setting",
                                            "billing_class", "payer", "plan", "price_type", "dup_seq", "amount", "methodology",
                                            "modifiers", "row_hash"))
    changes = con.execute(f"""
        SELECT c.row_id, c.key_hash, c.hospital_slug, c.description, c.code, c.code_type, c.alt_codes, c.setting, c.billing_class,
               c.payer, c.plan, c.price_type, c.dup_seq, c.amount, c.methodology, c.modifiers, c.row_hash, c.first_source_sha256,
               c.effective_from, {ts} AS effective_to, false AS is_current, '{sha}' AS closed_by_source_sha256,
               CASE WHEN s.key_hash IS NULL THEN 'removed' ELSE 'changed' END AS change_reason, 'close' AS action
        FROM cur c LEFT JOIN stg s ON s.key_hash = c.key_hash
        WHERE s.key_hash IS NULL OR s.row_hash <> c.row_hash
        UNION ALL
        SELECT md5(s.key_hash || '|{sha}'), {new_cols}, '{sha}', {ts}, cast(NULL as timestamptz), true,
               cast(NULL as varchar), cast(NULL as varchar), 'insert'
        FROM stg s LEFT JOIN cur c ON s.key_hash = c.key_hash
        WHERE c.key_hash IS NULL OR c.row_hash <> s.row_hash
    """).to_arrow_table()
    n_unchanged = con.execute("SELECT count(*) FROM stg s JOIN cur c USING (key_hash) WHERE s.row_hash = c.row_hash").fetchone()[0]
    con.close()
    n_close = int(pa.compute.sum(pa.compute.equal(changes["action"], "close")).as_py() or 0) if changes.num_rows else 0
    n_insert = changes.num_rows - n_close
    if changes.num_rows == 0:
        return {"mode": "noop", "rows_inserted": 0, "rows_closed": 0, "rows_unchanged": n_unchanged}
    src = changes.drop_columns(["action"]).cast(HISTORY_SCHEMA)
    upd = {k: f"s.{k}" for k in ("effective_to", "is_current", "closed_by_source_sha256", "change_reason")}
    (dt.merge(src, "t.hospital_slug = s.hospital_slug AND t.row_id = s.row_id", source_alias="s", target_alias="t")
       .when_matched_update(upd).when_not_matched_insert({c: f"s.{c}" for c in COLS}).execute())
    return {"mode": "merge", "rows_inserted": n_insert, "rows_closed": n_close, "rows_unchanged": n_unchanged}


def ledger_records(ledger: Path) -> list[dict]:
    if not DeltaTable.is_deltatable(str(ledger)):
        return []
    return DeltaTable(str(ledger)).to_pyarrow_table().to_pylist()


def ledger_append(ledger: Path, rec: dict) -> None:
    row = {k: rec.get(k) for k in LEDGER_SCHEMA.names}
    write_deltalake(str(ledger), pa.Table.from_pylist([row], schema=LEDGER_SCHEMA), mode="append")


def load_version(history: Path, ledger: Path, slug: str, sha: str, silver_glob: str, tmp: Path, synthetic: bool = False,
                 now: datetime | None = None) -> dict:
    """Idempotent: a (slug, sha) already in the ledger is skipped. Stage -> initial append or SCD2 merge -> ledger."""
    from pricecheck.history.stage import stage
    if any(r["slug"] == slug and r["source_sha256"] == sha for r in ledger_records(ledger)):
        return {"slug": slug, "source_sha256": sha, "mode": "skipped_already_loaded"}
    t0 = time.monotonic()
    now = now or datetime.now(timezone.utc)
    staged = tmp / f"staged_{slug}_{sha[:12]}.parquet"
    st = stage(silver_glob, staged, tmp)
    res = apply_version(history, slug, staged, sha, now, tmp) if has_rows(history, slug) else initial_load(history, staged, sha, now, tmp)
    staged.unlink(missing_ok=True)
    version = DeltaTable(str(history)).version()
    rec = {"slug": slug, "source_sha256": sha, "loaded_at": now, "staged_rows": st["staged_rows"], "history_version_after": version,
           "duration_s": round(time.monotonic() - t0, 1), "synthetic": synthetic, **res}
    ledger_append(ledger, rec)
    return {**rec, "stage": st}
