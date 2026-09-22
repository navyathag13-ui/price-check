"""Load the 4 gold marts from local DuckDB into Azure SQL Database, then apply the T-SQL views.

Never provisions anything -- the database must already exist (see sql/azure_sql/README.md for the az command,
which uses the free offer). Reads connection details from environment variables, never hardcoded:
  AZURE_SQL_SERVER      e.g. pricecheck-sql.database.windows.net
  AZURE_SQL_DATABASE    e.g. pricecheck
  AZURE_SQL_USER, AZURE_SQL_PASSWORD
Row counts loaded are printed and are real (not the 41.1M fact_price grain -- see DECISIONS.md ADR-020)."""
from __future__ import annotations

import os
import time
from pathlib import Path

import duckdb
import pymssql

ROOT = Path(__file__).resolve().parents[3]
DUCKDB_PATH = ROOT / "data/gold/pricecheck.duckdb"
SQL_DIR = ROOT / "sql/azure_sql"
TABLES = ["dim_hospital", "dim_procedure_code", "mart_price_comparison", "mart_hospital_quality"]


def run_script(cur, path: Path) -> None:
    for batch in path.read_text().split("\nGO\n"):
        b = batch.strip()
        if b:
            cur.execute(b)


def main() -> None:
    server, db = os.environ["AZURE_SQL_SERVER"], os.environ["AZURE_SQL_DATABASE"]
    user, pwd = os.environ["AZURE_SQL_USER"], os.environ["AZURE_SQL_PASSWORD"]
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    sql = pymssql.connect(server=server, user=user, password=pwd, database=db, login_timeout=30, timeout=120)
    cur = sql.cursor()
    print("applying schema + views ...")
    run_script(cur, SQL_DIR / "001_schema.sql")
    sql.commit()
    for table in TABLES:
        t0 = time.monotonic()
        df = con.execute(f"SELECT * FROM {table}").df()
        cols = list(df.columns)
        placeholders = ", ".join("%s" for _ in cols)
        insert = f"INSERT INTO dbo.{table} ({', '.join(cols)}) VALUES ({placeholders})"
        rows = [tuple(r) for r in df.itertuples(index=False)]
        cur.executemany(insert, rows)
        sql.commit()
        print(f"{table:28s} {len(rows):>8,} rows  {round(time.monotonic()-t0,1)}s")
    run_script(cur, SQL_DIR / "002_views.sql")
    sql.commit()
    cur.execute("SELECT COUNT(*) FROM dbo.vw_price_spread")
    print("vw_price_spread row count (verified live):", cur.fetchone()[0])
    sql.close()


if __name__ == "__main__":
    main()
