"""Strawberry GraphQL endpoint over the same db.py query layer as the REST API -- same data, same disclaimer."""
from __future__ import annotations

from typing import Optional

import strawberry
from strawberry.fastapi import GraphQLRouter

from pricecheck.serving import db
from pricecheck.serving.constants import DISCLAIMER


@strawberry.type
class Procedure:
    code: str
    code_type: str
    example_description: Optional[str]
    hospital_count: int
    price_row_count: int


@strawberry.type
class PriceSpread:
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


@strawberry.type
class HospitalQuality:
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


@strawberry.type
class Query:
    disclaimer: str = strawberry.field(resolver=lambda: DISCLAIMER)

    @strawberry.field
    def search_procedures(self, q: str, limit: int = 20) -> list[Procedure]:
        return [Procedure(**r) for r in db.search_procedures(q, limit)]

    @strawberry.field
    def price_spread(self, code: str) -> list[PriceSpread]:
        return [PriceSpread(**r) for r in db.price_spread(code)]

    @strawberry.field
    def hospital_quality(self, slug: Optional[str] = None) -> list[HospitalQuality]:
        return [HospitalQuality(**r) for r in db.hospital_quality(slug)]


schema = strawberry.Schema(query=Query)
graphql_router = GraphQLRouter(schema)
