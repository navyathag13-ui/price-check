"""Query layer with two backends, resolved the same way llm_service.py resolves LLM providers in the RAG project:
Azure SQL if AZURE_SQL_* is fully set, else the local DuckDB gold database (dbt's build output) -- always works,
zero cloud dependency. Every query function is written once, dispatched per-backend, so callers never branch."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[3]
DUCKDB_PATH = ROOT / "data/gold/pricecheck.duckdb"


@dataclass
class Backend:
    kind: str   # "azure_sql" | "duckdb"


def resolve() -> Backend:
    if all(os.environ.get(k) for k in ("AZURE_SQL_SERVER", "AZURE_SQL_DATABASE", "AZURE_SQL_USER", "AZURE_SQL_PASSWORD")):
        return Backend("azure_sql")
    return Backend("duckdb")


def _azure_conn():
    import pymssql
    return pymssql.connect(server=os.environ["AZURE_SQL_SERVER"], database=os.environ["AZURE_SQL_DATABASE"],
                           user=os.environ["AZURE_SQL_USER"], password=os.environ["AZURE_SQL_PASSWORD"],
                           login_timeout=15, timeout=30, as_dict=True)


# Same query text works on both backends: DuckDB and T-SQL agree on this simple SELECT/WHERE/ORDER/LIMIT subset.
Q_SEARCH = "SELECT code, code_type, example_description, hospital_count, price_row_count FROM {v} WHERE example_description LIKE '%' || ? || '%' ORDER BY hospital_count DESC LIMIT ?"
Q_SEARCH_TSQL = "SELECT TOP (%s) code, code_type, example_description, hospital_count, price_row_count FROM vw_procedure_search WHERE example_description LIKE '%' + %s + '%' ORDER BY hospital_count DESC"
Q_SPREAD = "SELECT code, code_type, example_description, price_type, n_hospitals, n_payers, n_prices, min_amount, median_amount, max_amount, max_to_min_ratio, n_flagged, pct_flagged FROM {v} WHERE code = ? ORDER BY price_type"
Q_SPREAD_TSQL = "SELECT code, code_type, example_description, price_type, n_hospitals, n_payers, n_prices, min_amount, median_amount, max_amount, max_to_min_ratio, n_flagged, pct_flagged FROM vw_price_spread WHERE code = %s ORDER BY price_type"
Q_QUALITY = "SELECT hospital_slug, hospital_name, state, quality_score, completeness, validity, consistency, freshness, days_since_last_update, total_prices, flagged_prices, pct_flagged, quality_band FROM {v} ORDER BY quality_score DESC"
Q_QUALITY_TSQL = "SELECT hospital_slug, hospital_name, state, quality_score, completeness, validity, consistency, freshness, days_since_last_update, total_prices, flagged_prices, pct_flagged, quality_band FROM vw_hospital_quality ORDER BY quality_score DESC"
Q_ONE_HOSPITAL_QUALITY_TSQL = Q_QUALITY_TSQL.replace("ORDER BY quality_score DESC", "WHERE hospital_slug = %s")


def search_procedures(text: str, limit: int = 20) -> list[dict[str, Any]]:
    b = resolve()
    if b.kind == "duckdb":
        con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
        rows = con.execute(Q_SEARCH.format(v="dim_procedure_code"), [text, limit]).fetchall()
        return [dict(zip(["code", "code_type", "example_description", "hospital_count", "price_row_count"], r)) for r in rows]
    conn = _azure_conn(); cur = conn.cursor(as_dict=True)
    cur.execute(Q_SEARCH_TSQL, (limit, text)); return list(cur.fetchall())


def price_spread(code: str) -> list[dict[str, Any]]:
    b = resolve()
    if b.kind == "duckdb":
        con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
        rows = con.execute(Q_SPREAD.format(v="vw_price_spread") if False else
                           "SELECT c.code, c.code_type, d.example_description, c.price_type, c.n_hospitals, c.n_payers, c.n_prices, "
                           "c.min_amount, c.median_amount, c.max_amount, "
                           "CASE WHEN c.min_amount > 0 THEN round(c.max_amount / c.min_amount, 1) END AS max_to_min_ratio, c.n_flagged, "
                           "CASE WHEN c.n_prices > 0 THEN round(100.0 * c.n_flagged / c.n_prices, 2) ELSE 0 END AS pct_flagged "
                           "FROM mart_price_comparison c JOIN dim_procedure_code d ON d.code = c.code AND d.code_type = c.code_type "
                           "WHERE c.code = ? ORDER BY c.price_type", [code]).fetchall()
        cols = ["code", "code_type", "example_description", "price_type", "n_hospitals", "n_payers", "n_prices",
                "min_amount", "median_amount", "max_amount", "max_to_min_ratio", "n_flagged", "pct_flagged"]
        return [dict(zip(cols, r)) for r in rows]
    conn = _azure_conn(); cur = conn.cursor(as_dict=True)
    cur.execute(Q_SPREAD_TSQL, (code,)); return list(cur.fetchall())


def hospital_quality(slug: str | None = None) -> list[dict[str, Any]]:
    b = resolve()
    if b.kind == "duckdb":
        con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
        base = ("SELECT hospital_slug, hospital_name, state, quality_score, completeness, validity, consistency, freshness, "
                "days_since_last_update, total_prices, flagged_prices, pct_flagged, "
                "CASE WHEN quality_score>=90 THEN 'good' WHEN quality_score>=75 THEN 'fair' ELSE 'needs review' END AS quality_band "
                "FROM mart_hospital_quality")
        cols = ["hospital_slug", "hospital_name", "state", "quality_score", "completeness", "validity", "consistency", "freshness",
                "days_since_last_update", "total_prices", "flagged_prices", "pct_flagged", "quality_band"]
        if slug:
            rows = con.execute(base + " WHERE hospital_slug = ?", [slug]).fetchall()
        else:
            rows = con.execute(base + " ORDER BY quality_score DESC").fetchall()
        return [dict(zip(cols, r)) for r in rows]
    conn = _azure_conn(); cur = conn.cursor(as_dict=True)
    if slug:
        cur.execute(Q_ONE_HOSPITAL_QUALITY_TSQL, (slug,))
    else:
        cur.execute(Q_QUALITY_TSQL)
    return list(cur.fetchall())


def health() -> dict[str, Any]:
    b = resolve()
    if b.kind == "duckdb":
        con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
        n_codes, n_hosp = con.execute("SELECT (SELECT count(*) FROM dim_procedure_code), (SELECT count(*) FROM dim_hospital)").fetchone()
        return {"status": "healthy", "backend": "duckdb", "gold_db_path": str(DUCKDB_PATH), "codes": n_codes, "hospitals": n_hosp}
    conn = _azure_conn(); cur = conn.cursor(as_dict=True)
    cur.execute("SELECT (SELECT COUNT(*) FROM dbo.dim_procedure_code) AS n_codes, (SELECT COUNT(*) FROM dbo.dim_hospital) AS n_hosp")
    r = cur.fetchone()
    return {"status": "healthy", "backend": "azure_sql", "server": os.environ["AZURE_SQL_SERVER"], "codes": r["n_codes"], "hospitals": r["n_hosp"]}
