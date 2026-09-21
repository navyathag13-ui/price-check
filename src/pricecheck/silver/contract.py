"""Versioned per-source data contracts and file-level validation."""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_DIR = ROOT / "contracts"

WIDE_GROUPS = ("standard_charge", "estimated_amount", "median_amount", "10th_percentile", "90th_percentile",
               "count", "additional_payer_notes")
WIDE_SUFFIXES = ("negotiated_dollar", "negotiated_percentage", "negotiated_algorithm", "methodology")
WIDE_FIXED_PREFIX = ("code|",)
_GENERIC_STD = {"standard_charge|gross", "standard_charge|discounted_cash", "standard_charge|min", "standard_charge|max"}

TALL_CANDIDATES = ["description", "code|1", "code|1|type", "setting", "billing_class", "standard_charge|gross",
                   "standard_charge|discounted_cash", "payer_name", "plan_name", "standard_charge|negotiated_dollar",
                   "standard_charge|min", "standard_charge|max"]
WIDE_CANDIDATES = ["description", "code|1", "code|1|type", "setting", "billing_class", "standard_charge|gross",
                   "standard_charge|discounted_cash", "standard_charge|min", "standard_charge|max"]
JSON_TOP_REQUIRED = ["hospital_name", "last_updated_on", "version", "standard_charge_information"]


class Contract(BaseModel):
    source: str
    contract_version: int = 1
    layout: Literal["csv_tall", "csv_wide", "json"]
    accepted_template_versions: list[str]
    deprecated_template_versions: list[str] = Field(default_factory=list)
    required_columns: list[str]
    expected_fixed_columns: list[str] = Field(default_factory=list)
    known_deviations: list[str] = Field(default_factory=list)
    allowed_settings: list[str] = ["inpatient", "outpatient", "both"]
    allowed_billing_classes: list[str] = ["facility", "professional", "both"]
    amount_max: Decimal = Decimal("100000000")
    max_reject_rate: float = 0.20
    min_data_rows: int = 1


def load(source: str) -> Contract:
    return Contract(**yaml.safe_load((CONTRACT_DIR / f"{source}.v1.yaml").read_text()))


def split_wide_header(col: str) -> tuple[str, str, str, str] | None:
    """'standard_charge|Aetna|PPO|negotiated_dollar' -> (group, payer, plan, suffix). None if not payer-specific."""
    parts = col.split("|")
    if parts[0] not in WIDE_GROUPS or len(parts) < 3 or col in _GENERIC_STD:
        return None
    suffix = parts[-1] if parts[-1] in WIDE_SUFFIXES else ""
    core = parts[1:-1] if suffix else parts[1:]
    if len(core) < 2:
        return None
    return parts[0], core[0], "|".join(core[1:]), suffix


def validate_header(c: Contract, layout: str, version: str | None, columns: list[str]) -> tuple[list[str], list[str]]:
    """Returns (violations -> quarantine, warnings -> alert only)."""
    errors: list[str] = []
    warns: list[str] = []
    if layout != c.layout:
        errors.append(f"layout changed: contract={c.layout} observed={layout}")
    if version not in c.accepted_template_versions:
        errors.append(f"template version {version!r} not in accepted {c.accepted_template_versions}")
    elif version in c.deprecated_template_versions:
        warns.append(f"template version {version} is deprecated")
    missing = [x for x in c.required_columns if x not in set(columns)]
    if missing:
        errors.append(f"missing required columns: {missing}")
    if c.layout != "json" and c.expected_fixed_columns:
        fixed_now = [x for x in columns if c.layout == "csv_tall" or split_wide_header(x) is None]
        new = sorted(set(fixed_now) - set(c.expected_fixed_columns))
        gone = sorted(set(c.expected_fixed_columns) - set(fixed_now))
        if new:
            warns.append(f"column drift: new non-payer columns {new[:8]}")
        if gone:
            warns.append(f"column drift: expected columns gone {gone[:8]}")
    return errors, warns
