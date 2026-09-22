"""Export current history rows as Parquet and carve deterministic subsets by key hash (same data distribution at every size)."""
from pathlib import Path

from pricecheck.history import delta_store as D

ROOT = Path(__file__).resolve().parents[3]; B = ROOT / "data/bench"
SUBSETS = {"s1m": 24, "s5m": 122, "s20m": 490, "full": 1000}      # per-mille of rows kept

if __name__ == "__main__":
    con = D.duck(); con.execute(f"SET memory_limit='11GB'; SET temp_directory='{ROOT / 'data/tmp'}'")
    for name, pm in SUBSETS.items():
        out = B / name; out.mkdir(parents=True, exist_ok=True)
        con.execute(f"""COPY (SELECT hospital_slug, code, code_type, description, setting, billing_class, price_type, payer, plan,
                                cast(amount AS double) AS amount, key_hash FROM delta_scan('{ROOT}/data/delta/price_history')
                                WHERE is_current AND hash(key_hash) % 1000 < {pm}) TO '{out}' (FORMAT parquet, COMPRESSION zstd, FILE_SIZE_BYTES '128MB')""")
        n = con.execute(f"SELECT count(*) FROM read_parquet('{out}/*.parquet')").fetchone()[0]
        print(name, f"{n:,} rows", f"{sum(f.stat().st_size for f in out.glob('*.parquet'))/1e6:,.0f} MB")
