"""FastAPI service over the gold layer. See db.py for the DuckDB/Azure SQL backend resolution.

Disclaimer required by the project brief: this surfaces published hospital price-transparency data for comparison.
It is not medical or financial advice, and is stated as such in every response's `disclaimer` field, not just docs."""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from pricecheck.serving import db
from pricecheck.serving.constants import DISCLAIMER
from pricecheck.serving.graphql_app import graphql_router

app = FastAPI(title="Price Check API", version="1.0.0",
              description="Compare published hospital prices for the same procedure. " + DISCLAIMER)
app.include_router(graphql_router, prefix="/graphql")


class ProcedureHit(BaseModel):
    code: str
    code_type: str
    example_description: Optional[str]
    hospital_count: int
    price_row_count: int


class SpreadRow(BaseModel):
    code: str
    code_type: str
    example_description: Optional[str]
    price_type: str
    n_hospitals: int
    n_payers: int
    n_prices: int
    min_amount: float
    median_amount: float
    max_amount: float
    max_to_min_ratio: Optional[float]
    n_flagged: int
    pct_flagged: float


class HospitalQuality(BaseModel):
    hospital_slug: str
    hospital_name: str
    state: Optional[str]
    quality_score: Optional[float]
    completeness: Optional[float]
    validity: Optional[float]
    consistency: Optional[float]
    freshness: Optional[float]
    days_since_last_update: Optional[int]
    total_prices: int
    flagged_prices: int
    pct_flagged: float
    quality_band: str


@app.get("/health")
def health():
    return {**db.health(), "disclaimer": DISCLAIMER}


@app.get("/procedures/search", response_model=list[ProcedureHit])
def search(q: str = Query(..., min_length=2), limit: int = Query(20, ge=1, le=100)):
    return db.search_procedures(q, limit)


@app.get("/procedures/{code}/spread", response_model=dict)
def spread(code: str):
    rows = db.price_spread(code)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No price data for code '{code}'. Try /procedures/search first.")
    return {"code": code, "disclaimer": DISCLAIMER, "by_price_type": rows}


@app.get("/hospitals/quality", response_model=list[HospitalQuality])
def hospitals_quality():
    return db.hospital_quality()


@app.get("/hospitals/{slug}/quality", response_model=HospitalQuality)
def hospital_quality_one(slug: str):
    rows = db.hospital_quality(slug)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No hospital '{slug}'.")
    return rows[0]
