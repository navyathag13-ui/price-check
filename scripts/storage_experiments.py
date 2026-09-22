"""Delta storage/query experiments on the real 41.1M-row table: same queries before/after each change.

Variants (all hold the identical 41,134,669 rows; written from data/bench/full):
  V0  real table as loaded (partitioned by hospital_slug, 52 files ~100MB)  -- baseline
  V1  unpartitioned, FRAGMENTED: 400 small appends (simulates a long history of incremental loads)  [simulated]
  V2  V1 after OPTIMIZE (compaction to ~128MB files)
  V3  V2 after Z-ORDER BY (code)
  V4  V0 layout + Z-ORDER BY (code) inside each hospital partition
  V5  Spark liquid clustering CLUSTER BY (code)
Queries (identical text on every variant, DuckDB delta_scan): Q1 one code across hospitals; Q2 one hospital + type + 10 codes;
Q3 full-table aggregate. Timing: median of 5 runs after 1 warm-up. Files-skippable is computed exactly from Delta min/max stats."""
import json, shutil, statistics, sys, time
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq
from deltalake import DeltaTable, write_deltalake
from pricecheck.history import delta_store as D

ROOT = Path(__file__).resolve().parents[1]; W = ROOT / "data/storage_exp"; SRC = ROOT / "data/bench/full"
CODE = "11043"
Q = {
    "Q1_one_code": f"SELECT price_type, count(*), min(amount), median(amount), max(amount) FROM t WHERE code = '{CODE}' GROUP BY 1 ORDER BY 1",
    "Q2_hospital_type_codes": "SELECT count(*), avg(amount) FROM t WHERE hospital_slug = 'sanford-usd' AND price_type = 'cash' AND code IN "
                              "('11043','99213','70553','73721','93000','80053','85025','36415','71046','81001')",
    "Q3_full_aggregate": "SELECT code, price_type, count(*), avg(amount) FROM t GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 5",
}
COLS = ["hospital_slug", "code", "code_type", "description", "setting", "billing_class", "price_type", "payer", "plan", "amount", "key_hash"]


def size_gb(p):
    return round(sum(f.stat().st_size for f in Path(p).rglob("*.parquet")) / 1e9, 2)


def files_info(p, code=CODE):
    dt = DeltaTable(str(p)); a = pa.table(dt.get_add_actions(flatten=True)).to_pandas()
    lo, hi = a["min.code"], a["max.code"]
    return {"files": int(len(a)), "median_file_mb": round(float(a.size_bytes.median() / 1e6), 1),
            "files_whose_code_range_contains_Q1_code": int(((lo <= code) & (hi >= code)).sum())}


def time_queries(p):
    con = D.duck(); con.execute("SET threads=10")
    out = {}
    for name, q in Q.items():
        sql = q.replace("FROM t", f"FROM delta_scan('{p}')")
        con.execute(sql).fetchall()                        # warm-up
        ts = []
        for _ in range(5):
            t = time.perf_counter(); con.execute(sql).fetchall(); ts.append(time.perf_counter() - t)
        out[name] = round(statistics.median(ts), 3)
    return out


def write_from_parquet(path, chunk_rows=None, partition_by=None, n_appends=None):
    shutil.rmtree(path, ignore_errors=True)
    pf = [pq.ParquetFile(f) for f in sorted(SRC.glob("*.parquet"))]
    batches = (b for f in pf for b in f.iter_batches(batch_size=chunk_rows or 1_000_000, columns=COLS))
    if n_appends:
        for i, b in enumerate(batches):
            write_deltalake(str(path), pa.Table.from_batches([b]), mode="append")
    else:
        write_deltalake(str(path), pa.RecordBatchReader.from_batches(pa.schema([f for f in pf[0].schema_arrow if f.name in COLS]), batches),
                        partition_by=partition_by)


def main():
    res = {}; W.mkdir(exist_ok=True)
    real = ROOT / "data/delta/price_history"
    res["V0_real_partitioned_by_hospital"] = {**files_info(real), "size_gb": size_gb(real), "timings_s": time_queries(real)}
    print("V0", res["V0_real_partitioned_by_hospital"], flush=True)
    v1 = W / "v1_fragmented"; write_from_parquet(v1, chunk_rows=100_000, n_appends=True)
    res["V1_fragmented_unpartitioned_SIMULATED"] = {**files_info(v1), "size_gb": size_gb(v1), "timings_s": time_queries(v1)}
    print("V1", res["V1_fragmented_unpartitioned_SIMULATED"], flush=True)
    t = time.perf_counter(); DeltaTable(str(v1)).optimize.compact(target_size=128 * 1024 * 1024); opt_s = round(time.perf_counter() - t, 1)
    res["V2_after_compaction"] = {**files_info(v1), "size_gb": size_gb(v1), "timings_s": time_queries(v1), "optimize_seconds": opt_s}
    print("V2", res["V2_after_compaction"], flush=True)
    t = time.perf_counter(); DeltaTable(str(v1)).optimize.z_order(["code"], target_size=128 * 1024 * 1024); z_s = round(time.perf_counter() - t, 1)
    res["V3_after_zorder_code"] = {**files_info(v1), "size_gb": size_gb(v1), "timings_s": time_queries(v1), "zorder_seconds": z_s}
    print("V3", res["V3_after_zorder_code"], flush=True)
    json.dump(res, open(ROOT / "docs/storage_experiments.json", "w"), indent=1)


if __name__ == "__main__":
    main()
