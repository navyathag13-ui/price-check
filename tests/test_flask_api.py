"""Flask REST service: same answers as the FastAPI app, input validation, JSON errors and the pandas compare endpoint."""

import pytest
from fastapi.testclient import TestClient

from pricecheck.serving import db

pytestmark = pytest.mark.skipif(not db.DUCKDB_PATH.exists(), reason="gold DuckDB not built (run dbt build first)")

flask_app = __import__("pricecheck.serving.flask_api", fromlist=["app"]).app
flask_client = flask_app.test_client()
fastapi_client = TestClient(__import__("pricecheck.serving.api", fromlist=["app"]).app)


def test_health_has_backend_and_disclaimer():
    r = flask_client.get("/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["backend"] == "duckdb" and body["hospitals"] == 21
    assert "not medical or financial advice" in body["disclaimer"]


def test_search_matches_fastapi():
    flask_rows = flask_client.get("/procedures/search?q=mri&limit=5").get_json()
    fastapi_rows = fastapi_client.get("/procedures/search", params={"q": "mri", "limit": 5}).json()
    assert flask_rows and flask_rows == fastapi_rows


def test_spread_matches_fastapi():
    flask_body = flask_client.get("/procedures/99213/spread").get_json()
    fastapi_body = fastapi_client.get("/procedures/99213/spread").json()
    # FastAPI's untyped /spread response sends DuckDB Decimals as strings ("208.88"); Flask sends numbers. Same values.
    money = ("min_amount", "median_amount", "max_amount")
    as_numbers = [{k: float(v) if k in money else v for k, v in r.items()} for r in fastapi_body["by_price_type"]]
    assert flask_body["by_price_type"] == as_numbers
    assert all(r["min_amount"] <= r["median_amount"] <= r["max_amount"] for r in flask_body["by_price_type"])


def test_hospital_quality_list_and_one():
    rows = flask_client.get("/hospitals/quality").get_json()
    assert len(rows) == 21
    one = flask_client.get(f"/hospitals/{rows[0]['hospital_slug']}/quality").get_json()
    assert one == rows[0]


@pytest.mark.parametrize("url,status,fragment", [
    ("/procedures/search?q=m", 400, "at least 2 characters"),
    ("/procedures/search", 400, "at least 2 characters"),
    ("/procedures/search?q=mri&limit=abc", 400, "must be an integer"),
    ("/procedures/search?q=mri&limit=500", 400, "between 1 and 100"),
    ("/procedures/ZZZZZ-not-a-real-code/spread", 404, "No price data"),
    ("/hospitals/not-a-real-hospital/quality", 404, "No hospital"),
    ("/procedures/compare?codes=99213", 400, "at least 2 codes"),
    ("/procedures/compare?codes=" + ",".join(str(c) for c in range(11)), 400, "at most 10"),
    ("/no-such-route", 404, "not found"),
])
def test_errors_are_json_with_disclaimer(url, status, fragment):
    r = flask_client.get(url)
    assert r.status_code == status
    body = r.get_json()
    assert fragment.lower() in body["error"].lower() and body["disclaimer"]


def test_compare_ranks_medians_within_each_price_type():
    body = flask_client.get("/procedures/compare?codes=99213,99214,ZZZZZ").get_json()
    assert body["codes"] == ["99213", "99214", "ZZZZZ"] and body["missing"] == ["ZZZZZ"]
    rows = body["rows"]
    assert {r["code"] for r in rows} == {"99213", "99214"}
    for price_type in {r["price_type"] for r in rows}:
        group = [r for r in rows if r["price_type"] == price_type]
        medians = [r["median_amount"] for r in group]
        assert medians == sorted(medians)
        assert [r["rank_in_price_type"] for r in group][0] == 1


def test_compare_values_agree_with_the_query_layer():
    rows = flask_client.get("/procedures/compare?codes=99213,99214").get_json()["rows"]
    source = {(r["code"], r["code_type"], r["price_type"]): r for code in ("99213", "99214") for r in db.price_spread(code)}
    assert len(rows) == len(source)
    for r in rows:
        s = source[(r["code"], r["code_type"], r["price_type"])]
        assert r["median_amount"] == pytest.approx(float(s["median_amount"]), abs=0.01)
        assert r["spread"] == pytest.approx(float(s["max_amount"] - s["min_amount"]), abs=0.01)


def test_duplicate_codes_are_compared_once():
    body = flask_client.get("/procedures/compare?codes=99213,99213,99214").get_json()
    assert body["codes"] == ["99213", "99214"]
