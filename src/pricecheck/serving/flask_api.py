"""Flask REST service over the gold layer, alongside the FastAPI app in api.py.

Both apps call the same query layer (db.py), so they return the same rows from DuckDB or Azure SQL. This one adds
/procedures/compare, which uses pandas to put several procedure codes side by side (median and spread per price type).
Every JSON body carries the same disclaimer as the FastAPI app: data findings, not medical or financial advice.

Run:  flask --app pricecheck.serving.flask_api run --port 8001"""
from __future__ import annotations

from decimal import Decimal

import pandas as pd
from flask import Flask, jsonify, request
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException

from pricecheck.serving import db
from pricecheck.serving.constants import DISCLAIMER

MAX_COMPARE_CODES = 10


class NumberJSONProvider(DefaultJSONProvider):
    """DuckDB returns prices as Decimal; Flask would send them as strings, FastAPI sends numbers. Match FastAPI."""
    @staticmethod
    def default(o):
        if isinstance(o, Decimal):
            return float(o)
        return DefaultJSONProvider.default(o)


class BadRequest(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def _int_arg(name: str, default: int, lo: int, hi: int) -> int:
    raw = request.args.get(name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise BadRequest(f"'{name}' must be an integer, got '{raw}'.")
    if not lo <= value <= hi:
        raise BadRequest(f"'{name}' must be between {lo} and {hi}.")
    return value


def compare_codes(codes: list[str]) -> list[dict]:
    """Side-by-side medians for several codes: one row per code and price type, ranked by median within each type."""
    rows = [r for code in codes for r in db.price_spread(code)]
    if not rows:
        return []
    df = pd.DataFrame(rows)
    for col in ("median_amount", "min_amount", "max_amount", "pct_flagged"):
        df[col] = pd.to_numeric(df[col])
    df["spread"] = df["max_amount"] - df["min_amount"]
    df["rank_in_price_type"] = df.groupby("price_type")["median_amount"].rank(method="min").astype(int)
    cols = ["code", "code_type", "example_description", "price_type", "n_hospitals", "median_amount",
            "min_amount", "max_amount", "spread", "pct_flagged", "rank_in_price_type"]
    out = df[cols].sort_values(["price_type", "rank_in_price_type", "code", "code_type"])
    return out.round({"median_amount": 2, "min_amount": 2, "max_amount": 2, "spread": 2}).to_dict(orient="records")


def create_app() -> Flask:
    Flask.json_provider_class = NumberJSONProvider
    app = Flask(__name__)
    app.json.sort_keys = False

    @app.errorhandler(BadRequest)
    def bad_request(e: BadRequest):
        return jsonify(error=e.message, disclaimer=DISCLAIMER), e.status

    @app.errorhandler(HTTPException)
    def http_error(e: HTTPException):
        return jsonify(error=e.description, disclaimer=DISCLAIMER), e.code

    @app.get("/health")
    def health():
        return jsonify({**db.health(), "disclaimer": DISCLAIMER})

    @app.get("/procedures/search")
    def search():
        q = (request.args.get("q") or "").strip()
        if len(q) < 2:
            raise BadRequest("'q' must be at least 2 characters.")
        return jsonify(db.search_procedures(q, _int_arg("limit", 20, 1, 100)))

    @app.get("/procedures/<code>/spread")
    def spread(code: str):
        rows = db.price_spread(code)
        if not rows:
            raise BadRequest(f"No price data for code '{code}'. Try /procedures/search first.", 404)
        return jsonify(code=code, disclaimer=DISCLAIMER, by_price_type=rows)

    @app.get("/procedures/compare")
    def compare():
        codes = list(dict.fromkeys(c.strip() for c in (request.args.get("codes") or "").split(",") if c.strip()))
        if len(codes) < 2:
            raise BadRequest("Pass at least 2 codes, e.g. ?codes=99213,99214.")
        if len(codes) > MAX_COMPARE_CODES:
            raise BadRequest(f"Compare at most {MAX_COMPARE_CODES} codes at a time.")
        rows = compare_codes(codes)
        found = sorted({r["code"] for r in rows})
        return jsonify(codes=codes, missing=[c for c in codes if c not in found], disclaimer=DISCLAIMER, rows=rows)

    @app.get("/hospitals/quality")
    def hospitals_quality():
        return jsonify(db.hospital_quality())

    @app.get("/hospitals/<slug>/quality")
    def hospital_quality_one(slug: str):
        rows = db.hospital_quality(slug)
        if not rows:
            raise BadRequest(f"No hospital '{slug}'.", 404)
        return jsonify(rows[0])

    return app


app = create_app()
