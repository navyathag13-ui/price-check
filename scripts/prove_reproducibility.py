"""Proves, end to end, that a past report can be reproduced exactly after the data has moved on.

Sandbox: real silver rows for one hospital (Gundersen) in a scratch Delta table. Version 1 = the real file.
Version 2 = a SYNTHETIC change set derived from it (2% of prices +10%, 1% removed, 1% new lines), clearly labelled
synthetic in the ledger -- we only have one real version per hospital so far, and this tests the mechanism, not
hospital behaviour. Exit code 0 only if every check passes.
"""
import hashlib
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from deltalake import DeltaTable

from pricecheck.history import delta_store as D
from pricecheck.reports import median_price as R

ROOT = Path(__file__).resolve().parents[1]
SB = ROOT / "data/sandbox_repro"
HIST, LEDG, TMP, REP = SB / "history", SB / "ledger", SB / "tmp", SB / "reports/ledger.jsonl"
SLUG = "gundersen-lutheran"
checks = []


def check(name, ok, detail=""):
    checks.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


def main():
    shutil.rmtree(SB, ignore_errors=True)
    real = sorted((ROOT / f"data/silver/canonical/hospital={SLUG}").glob("source_sha256=*/part-*.parquet"))
    sha1 = real[0].parent.name.split("=")[1]
    glob1 = str(real[0].parent / "part-*.parquet")
    con = duckdb.connect()
    codes = [r[0] for r in con.execute(f"""SELECT code FROM read_parquet('{glob1}') WHERE price_type='negotiated' AND code_type IN ('CPT','HCPCS')
                                          GROUP BY code ORDER BY count(*) DESC, code LIMIT 15""").fetchall()]
    params = {"name": "price_spread_by_code", "version": 1, "price_types": ["negotiated", "cash"], "codes": codes}
    print(f"== Step 1: load REAL version 1 ({SLUG}, sha {sha1[:12]})")
    t1 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    r1 = D.load_version(HIST, LEDG, SLUG, sha1, glob1, TMP, now=t1)
    print(f"   mode={r1['mode']} rows_inserted={r1['rows_inserted']:,} history_version={r1['history_version_after']}")
    print("== Step 2: run + record report R1 against history version", r1["history_version_after"])
    rec1 = R.record(HIST, params, REP)
    print(f"   run_id={rec1['run_id']} rows={rec1['rows']} sha256={rec1['output_sha256'][:16]}...")

    print("== Step 3: ingest SYNTHETIC version 2 (data moves on)")
    syn = SB / "silver_v2"; syn.mkdir(parents=True)
    k = "hash(description || '|' || code || '|' || coalesce(payer,'') || '|' || price_type)"
    con.execute(f"""COPY (
        SELECT * REPLACE (CASE WHEN {k} % 50 = 0 THEN cast(amount * 1.10 as decimal(14,4)) ELSE amount END AS amount)
        FROM read_parquet('{glob1}') WHERE {k} % 100 <> 1
        UNION ALL
        SELECT * REPLACE (description || ' (NEW LINE)' AS description) FROM read_parquet('{glob1}') WHERE {k} % 100 = 2
    ) TO '{syn}/part-0.parquet' (FORMAT parquet)""")
    sha2 = "synthetic-" + hashlib.sha256(sha1.encode()).hexdigest()[:16]
    t2 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    r2 = D.load_version(HIST, LEDG, SLUG, sha2, str(syn / "part-0.parquet"), TMP, synthetic=True, now=t2)
    print(f"   mode={r2['mode']} inserted={r2['rows_inserted']:,} closed={r2['rows_closed']:,} unchanged={r2['rows_unchanged']:,} "
          f"history_version={r2['history_version_after']}")
    check("merge changed the table (new Delta version)", r2["history_version_after"] > r1["history_version_after"])
    check("merge touched only changed rows", r2["rows_unchanged"] > 0.9 * r1["rows_inserted"],
          f"({r2['rows_unchanged']:,} of {r1['rows_inserted']:,} untouched)")

    print("== Step 4: the current-state report has changed; the old one must still reproduce exactly")
    now_data, now_meta = R.run_report(HIST, params)
    check("report on latest version differs from R1 (data really moved)", now_meta["output_sha256"] != rec1["output_sha256"])
    rep = R.reproduce(rec1["run_id"], REP)
    check("R1 re-run via Delta time travel is byte-identical", rep["identical"], f"(v{rep['history_version']}, sha {rep['reproduced_sha256'][:16]}...)")

    print("== Step 5: independent cross-check with the SCD2 columns (no time travel)")
    asof, _ = R.run_report(HIST, params, as_of_ts=datetime(2026, 9, 15, tzinfo=timezone.utc))
    check("SCD2 point-in-time (2026-09-15) equals R1 bytes", hashlib.sha256(asof).hexdigest() == rec1["output_sha256"])

    print("== Step 6: history is queryable and complete")
    dt = DeltaTable(str(HIST)); cur = D.duck()
    tot, n_cur, n_closed = cur.execute(f"SELECT count(*), count(*) FILTER (is_current), count(*) FILTER (NOT is_current) FROM delta_scan('{HIST}')").fetchone()
    check("closed rows == rows_closed reported by MERGE", n_closed == r2["rows_closed"], f"({n_closed:,})")
    check("no row lost: total == v1 rows + inserted", tot == r1["rows_inserted"] + r2["rows_inserted"], f"({tot:,})")
    print(f"   history rows={tot:,} current={n_cur:,} closed={n_closed:,}; Delta versions={dt.version()+1}")
    ok = all(checks)
    print("\nRESULT:", "ALL CHECKS PASSED" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
