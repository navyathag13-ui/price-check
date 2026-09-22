"""Serving layer: backend resolution + REST/GraphQL responses against the real local gold DB."""

import pytest
from fastapi.testclient import TestClient

from pricecheck.serving import db

pytestmark = pytest.mark.skipif(not db.DUCKDB_PATH.exists(), reason="gold DuckDB not built (run dbt build first)")


def test_backend_resolves_to_duckdb_when_azure_env_unset(monkeypatch):
    for k in ("AZURE_SQL_SERVER", "AZURE_SQL_DATABASE", "AZURE_SQL_USER", "AZURE_SQL_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    assert db.resolve().kind == "duckdb"


def test_backend_resolves_to_azure_sql_only_when_all_four_vars_set(monkeypatch):
    monkeypatch.setenv("AZURE_SQL_SERVER", "x"); monkeypatch.setenv("AZURE_SQL_DATABASE", "x")
    monkeypatch.setenv("AZURE_SQL_USER", "x")
    assert db.resolve().kind == "duckdb"          # 3 of 4 set: still falls back
    monkeypatch.setenv("AZURE_SQL_PASSWORD", "x")
    assert db.resolve().kind == "azure_sql"


def test_search_and_spread_and_quality_return_real_rows():
    hits = db.search_procedures("mri", 5)
    assert hits and all(h["hospital_count"] >= 1 for h in hits)
    spread = db.price_spread(hits[0]["code"])
    assert spread and all(r["min_amount"] <= r["median_amount"] <= r["max_amount"] for r in spread)
    q = db.hospital_quality()
    assert len(q) == 21 and all(0 <= r["quality_score"] <= 100 for r in q)


client = TestClient(__import__("pricecheck.serving.api", fromlist=["app"]).app)


def test_api_health_reports_disclaimer_and_backend():
    r = client.get("/health")
    assert r.status_code == 200 and "not medical or financial advice" in r.json()["disclaimer"]


def test_api_search_and_spread_and_404():
    r = client.get("/procedures/search", params={"q": "mri"}); assert r.status_code == 200 and r.json()
    code = r.json()[0]["code"]
    r2 = client.get(f"/procedures/{code}/spread"); assert r2.status_code == 200 and r2.json()["by_price_type"]
    r3 = client.get("/procedures/ZZZZZ-not-a-real-code/spread"); assert r3.status_code == 404


def test_api_hospital_quality_list_and_one():
    r = client.get("/hospitals/quality"); assert r.status_code == 200 and len(r.json()) == 21
    slug = r.json()[0]["hospital_slug"]
    r2 = client.get(f"/hospitals/{slug}/quality"); assert r2.status_code == 200 and r2.json()["hospital_slug"] == slug
    assert client.get("/hospitals/not-a-real-hospital/quality").status_code == 404


def test_graphql_matches_rest():
    q = '{ priceSpread(code: "99213") { code priceType medianAmount } }'
    r = client.post("/graphql", json={"query": q})
    assert r.status_code == 200
    gql_rows = r.json()["data"]["priceSpread"]
    rest_rows = client.get("/procedures/99213/spread").json()["by_price_type"]
    assert len(gql_rows) == len(rest_rows)
    assert {row["priceType"] for row in gql_rows} == {row["price_type"] for row in rest_rows}
