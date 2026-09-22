"""Run the three workloads on one engine at one size; append results to data/bench/results.jsonl.
usage: python -m pricecheck.bench.run --engine duck|spark --size s1m [--repeats 3]"""
import argparse, json, os, threading, time
from pathlib import Path
import psutil
from pricecheck.bench.workloads import DUCK, SPARK, sql

ROOT = Path(__file__).resolve().parents[3]; B = ROOT / "data/bench"
THREADS = 10


class Peak:
    """Peak RSS of this process plus children (the JVM is a child of the Python process under PySpark)."""
    def __enter__(self):
        self.p, self.peak, self.stop = psutil.Process(), 0, False
        def loop():
            while not self.stop:
                try:
                    self.peak = max(self.peak, self.p.memory_info().rss + sum(c.memory_info().rss for c in self.p.children(recursive=True)))
                except psutil.Error:
                    pass
                time.sleep(0.1)
        self.t = threading.Thread(target=loop, daemon=True); self.t.start(); return self
    def __exit__(self, *a):
        self.stop = True; self.t.join()


def digest(rows):
    return [[round(float(v), 6) if isinstance(v, float) else int(v) for v in r] for r in rows]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--engine", required=True); ap.add_argument("--size", required=True); ap.add_argument("--repeats", type=int, default=3)
    a = ap.parse_args(); path = B / a.size
    n_rows = None
    out = B / "results.jsonl"
    if a.engine == "duck":
        import duckdb
        wl = sql(DUCK); startup = 0.0
        def run(q):
            con = duckdb.connect(); con.execute(f"SET threads={THREADS}; SET memory_limit='11GB'; SET temp_directory='{ROOT / 'data/tmp'}'")
            con.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet('{path}/*.parquet')")
            return con.execute(q).fetchall()
        n_rows = duckdb.connect().execute(f"SELECT count(*) FROM read_parquet('{path}/*.parquet')").fetchone()[0]
    else:
        os.environ.setdefault("JAVA_HOME", str(Path.home() / ".local/share/jdk/jdk-17.0.20.1+1/Contents/Home"))
        from pyspark.sql import SparkSession
        t0 = time.perf_counter()
        spark = (SparkSession.builder.master(f"local[{THREADS}]").appName("bench").config("spark.driver.memory", "10g").config("spark.ui.enabled", "false")
                 .config("spark.sql.shuffle.partitions", "40").config("spark.local.dir", str(ROOT / "data/tmp")).getOrCreate())
        spark.sparkContext.setLogLevel("ERROR")
        spark.read.parquet(str(path)).createOrReplaceTempView("t")
        n_rows = spark.sql("SELECT count(*) FROM t").collect()[0][0]; startup = time.perf_counter() - t0
        wl = sql(SPARK)
        def run(q):
            return [tuple(r) for r in spark.sql(q).collect()]
    for name, q in wl.items():
        for i in range(a.repeats):
            with Peak() as pk:
                t = time.perf_counter(); res = run(q); dt = time.perf_counter() - t
            rec = {"engine": a.engine, "size": a.size, "rows": n_rows, "workload": name, "run": i, "seconds": round(dt, 3),
                   "peak_rss_mb": round(pk.peak / 1e6), "startup_seconds": round(startup, 2), "digest": digest(res), "threads": THREADS}
            with out.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            print(a.engine, a.size, name, i, rec["seconds"], "s", rec["peak_rss_mb"], "MB", flush=True)


if __name__ == "__main__":
    main()
