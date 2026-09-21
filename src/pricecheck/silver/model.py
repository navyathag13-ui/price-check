"""Canonical schema, code-type normalisation and amount parsing (pure functions, no I/O)."""
from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import pyarrow as pa

PRICE_TYPES = ("gross", "cash", "negotiated", "min", "max")
SETTINGS = {"inpatient", "outpatient", "both"}
BILLING_CLASSES = {"facility", "professional", "both"}

# Primary-code priority: prefer codes that identify the *procedure*, not the hospital's internal item.
CODE_PRIORITY = ["CPT", "HCPCS", "MS-DRG", "APR-DRG", "ICD-10-PCS", "NDC", "CDM", "RC", "LOCAL", "OTHER"]
_TYPE_ALIASES = {
    "CPT": "CPT", "CPT-4": "CPT", "HCPCS": "HCPCS", "MS-DRG": "MS-DRG", "MSDRG": "MS-DRG", "DRG": "MS-DRG",
    "APR-DRG": "APR-DRG", "ICD-10-PCS": "ICD-10-PCS", "ICD10PCS": "ICD-10-PCS", "NDC": "NDC",
    "CDM": "CDM", "RC": "RC", "LOCAL": "LOCAL", "EAPG": "OTHER", "TRIS-DRG": "OTHER", "APC": "OTHER",
}

CANONICAL_SCHEMA = pa.schema([
    ("hospital_slug", pa.string()), ("source_sha256", pa.string()), ("source_row", pa.int64()),
    ("description", pa.string()), ("code", pa.string()), ("code_type", pa.string()), ("alt_codes", pa.string()),
    ("setting", pa.string()), ("billing_class", pa.string()), ("payer", pa.string()), ("plan", pa.string()),
    ("price_type", pa.string()), ("amount", pa.decimal128(14, 4)), ("methodology", pa.string()),
    ("modifiers", pa.string()), ("template_version", pa.string()), ("contract_version", pa.int32()),
])
REJECT_SCHEMA = pa.schema([
    ("hospital_slug", pa.string()), ("source_sha256", pa.string()), ("source_row", pa.int64()),
    ("kind", pa.string()), ("reason", pa.string()), ("field", pa.string()), ("raw", pa.string()),
])


@dataclass
class Reject:
    source_row: int
    kind: str          # "row" (whole item unusable) or "price" (one price cell unusable)
    reason: str
    field: str = ""
    raw: str = ""


class Decoder:
    """utf-8 decoding that falls back to cp1252 per bad byte and counts how often it had to."""
    count = 0

    @classmethod
    def register(cls) -> None:
        def handler(err: UnicodeDecodeError):
            cls.count += err.end - err.start
            return err.object[err.start:err.end].decode("cp1252", errors="replace"), err.end
        codecs.register_error("cp1252_fallback", handler)


Decoder.register()

_AMOUNT_JUNK = re.compile(r"[,$\s]")


def parse_amount(raw: object, max_plausible: Decimal = Decimal("100000000")) -> tuple[Decimal | None, str | None]:
    """Return (amount, reject_reason). Blank -> (None, None): not a price, not an error."""
    if raw is None:
        return None, None
    s = _AMOUNT_JUNK.sub("", str(raw))
    if s == "" or s.lower() in ("null", "none"):
        return None, None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None, "non_numeric_amount"
    if not d.is_finite():
        return None, "non_numeric_amount"
    if d <= 0:
        return None, "non_positive_amount"
    if d > max_plausible:
        return None, "above_plausible_max"
    q = d.quantize(Decimal("0.0001"))
    if q <= 0:              # e.g. 4.9e-43 is positive but rounds to a $0.0000 "price"
        return None, "non_positive_amount"
    return q, None


def normalise_type(raw: str | None) -> str:
    return _TYPE_ALIASES.get((raw or "").strip().upper(), "OTHER")


def pick_codes(pairs: list[tuple[str, str]]) -> tuple[str | None, str | None, str]:
    """pairs: [(code, raw_type)]. Returns (primary_code, primary_type, alt_codes 'TYPE:code|TYPE:code')."""
    clean = [(c.strip(), normalise_type(t)) for c, t in pairs if c and c.strip()]
    if not clean:
        return None, None, ""
    clean.sort(key=lambda p: CODE_PRIORITY.index(p[1]))
    code, typ = clean[0]
    alts = "|".join(f"{t}:{c}" for c, t in clean[1:])
    return code, typ, alts
