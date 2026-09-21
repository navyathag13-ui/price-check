"""Unit tests for cleansing/parsing logic on tiny fixtures (all three layouts) + rejection logging."""
import io
import json
from decimal import Decimal

import pytest

from pricecheck.silver.contract import Contract, validate_header
from pricecheck.silver.model import Decoder, Reject
from pricecheck.silver.parsers import Ctx, parse_json, parse_tall, parse_wide


def con(layout, **kw):
    return Contract(source="t", layout=layout, accepted_template_versions=["3.0.0"], required_columns=[], **kw)


def run(fn, data: bytes, layout):
    ctx = Ctx(con(layout), "sha", "3.0.0")
    return list(fn(io.BytesIO(data), ctx)), ctx


TALL_HEAD = "hospital_name,last_updated_on,version\nH,2026-01-01,3.0.0\n"
TALL_COLS = ("description,code|1,code|1|type,code|2,code|2|type,setting,billing_class,standard_charge|gross,"
             "standard_charge|discounted_cash,payer_name,plan_name,standard_charge|negotiated_dollar,"
             "standard_charge|negotiated_percentage,standard_charge|min,standard_charge|max\n")


def test_tall_generic_prices_emitted_once_per_consecutive_item():
    rows = ("Asp,123,CPT,9,CDM,outpatient,facility,10,8,A,PPO,7,,1,20\n"
            "Asp,123,CPT,9,CDM,outpatient,facility,10,8,B,HMO,6,,1,20\n")
    out, ctx = run(parse_tall, (TALL_HEAD + TALL_COLS + rows).encode(), "csv_tall")
    kinds = [(r["price_type"], r["payer"]) for r in out]
    assert kinds.count(("gross", None)) == 1 and ("negotiated", "A") in kinds and ("negotiated", "B") in kinds
    assert all(r["code"] == "123" and r["code_type"] == "CPT" and r["alt_codes"] == "CDM:9" for r in out)
    assert ctx.stats.rows_in == 2


def test_tall_rejects_are_logged_with_reasons_not_dropped():
    rows = (",123,CPT,,,outpatient,facility,10,,,,,,,\n"          # missing description
            "X,,,,,outpatient,facility,10,,,,,,,\n"               # no code
            "X,1,CPT,,,weird,facility,10,,,,,,,\n"                # invalid setting
            "X,1,CPT,,,both,facility,N/A,-4,,,,,,\n"              # bad price cells
            "short,row\n")                                        # ragged
    out, _ = run(parse_tall, (TALL_HEAD + TALL_COLS + rows).encode(), "csv_tall")
    rejects = [o for o in out if isinstance(o, Reject)]
    assert sorted(r.reason for r in rejects) == sorted(
        ["missing_description", "no_code", "invalid_setting", "non_numeric_amount", "non_positive_amount", "ragged_row"])


def test_tall_percentage_only_negotiated_is_counted_not_rejected():
    rows = "X,1,CPT,,,both,facility,,,A,PPO,,80,,\n"
    out, ctx = run(parse_tall, (TALL_HEAD + TALL_COLS + rows).encode(), "csv_tall")
    assert not [o for o in out if isinstance(o, Reject)] and ctx.stats.non_dollar_negotiated == 1


def test_wide_melts_payer_columns_and_skips_blanks():
    data = ("h,v\nH,3.0.0\ndescription,code|1,code|1|type,setting,standard_charge|gross,standard_charge|Acme|Gold|negotiated_dollar,"
            "standard_charge|Acme|Gold|methodology,standard_charge|Beta|Silver|negotiated_dollar,median_amount|Acme|Gold\n"
            "Asp,123,CPT,both,10,8.5,fee schedule,,5\n").encode()
    out, ctx = run(parse_wide, data, "csv_wide")
    neg = [r for r in out if r["price_type"] == "negotiated"]
    assert len(neg) == 1 and neg[0]["payer"] == "Acme" and neg[0]["plan"] == "Gold" and neg[0]["amount"] == Decimal("8.5")
    assert neg[0]["methodology"] == "fee schedule" and ctx.stats.extra["payer_plan_columns"] == 2


def test_json_v3_and_bom_and_string_amounts():
    doc = {"hospital_name": "H", "version": "3.0.0", "standard_charge_information": [
        {"description": "Asp", "code_information": [{"code": "123", "type": "CPT"}], "standard_charges": [
            {"setting": "outpatient", "gross_charge": "10.0", "discounted_cash": "8", "minimum": "1", "maximum": "20",
             "payers_information": [{"payer_name": "A", "plan_name": "PPO", "standard_charge_dollar": "7.25", "methodology": "fee schedule"}]}]}]}
    out, _ = run(parse_json, b"\xef\xbb\xbf" + json.dumps(doc).encode(), "json")
    assert sorted(r["price_type"] for r in out) == ["cash", "gross", "max", "min", "negotiated"]
    assert [r for r in out if r["price_type"] == "negotiated"][0]["amount"] == Decimal("7.25")


def test_cp1252_bytes_are_decoded_and_counted():
    Decoder.count = 0
    rows = b"Caf\xa0e,123,CPT,,,both,facility,10,,,,,,,\n"          # 0xA0 invalid as UTF-8
    out, _ = run(parse_tall, (TALL_HEAD + TALL_COLS).encode() + rows, "csv_tall")
    assert out[0]["description"].startswith("Caf") and Decoder.count == 1


def test_contract_violations_vs_warnings():
    c = Contract(source="t", layout="csv_tall", accepted_template_versions=["2.0.0", "3.0.0"], deprecated_template_versions=["2.0.0"],
                 required_columns=["description", "code|1"], expected_fixed_columns=["description", "code|1"])
    assert validate_header(c, "csv_tall", "3.0.0", ["description", "code|1"]) == ([], [])
    errs, warns = validate_header(c, "csv_tall", "2.0.0", ["description", "code|1", "new_col"])
    assert not errs and any("deprecated" in w for w in warns) and any("drift" in w for w in warns)
    errs, _ = validate_header(c, "csv_wide", "9.9.9", ["description"])
    assert len(errs) == 3      # layout changed, unaccepted version, missing column
