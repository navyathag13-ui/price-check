"""SCD2 history + time-travel semantics on tiny snapshots."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from deltalake import DeltaTable

from pricecheck.history import delta_store as D
from pricecheck.silver.model import CANONICAL_SCHEMA

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def snap(tmp_path, name, rows):
    d = tmp_path / "silver" / name
    d.mkdir(parents=True, exist_ok=True)
    recs = []
    for i, (desc, code, payer, ptype, amt) in enumerate(rows):
        recs.append({"hospital_slug": "h", "source_sha256": name, "source_row": i, "description": desc, "code": code,
                     "code_type": "CPT", "alt_codes": "", "setting": "outpatient", "billing_class": "facility",
                     "payer": payer, "plan": "P" if payer else None, "price_type": ptype,
                     "amount": Decimal(str(amt)), "methodology": None, "modifiers": None, "template_version": "3.0.0", "contract_version": 1})
    pq.write_table(pa.Table.from_pylist(recs, schema=CANONICAL_SCHEMA), d / "part-0.parquet")
    return str(d / "*.parquet")


@pytest.fixture
def env(tmp_path):
    return tmp_path, tmp_path / "hist", tmp_path / "ledger", tmp_path / "tmp"


def load(env, name, rows, when):
    tmp_path, hist, led, tmp = env
    return D.load_version(hist, led, "h", name, snap(tmp_path, name, rows), tmp, now=when)


V1 = [("Asp", "111", None, "gross", 100), ("Asp", "111", "A", "negotiated", 80), ("Bnd", "222", "A", "negotiated", 50), ("Cst", "333", None, "cash", 10)]


def test_two_consecutive_merges_then_time_travel(env):
    r1 = load(env, "v1", V1, T0)
    r2 = load(env, "v2", [("Asp", "111", None, "gross", 101)] + V1[1:], T0 + timedelta(days=1))
    r3 = load(env, "v3", [("Asp", "111", None, "gross", 102)] + V1[1:], T0 + timedelta(days=2))
    assert r3["mode"] == "merge" and r3["rows_closed"] == 1 and r3["rows_inserted"] == 1
    con = D.duck()
    at = lambda v: dict(con.execute(f"SELECT description || price_type, amount FROM delta_scan('{env[1]}', version={v}) WHERE is_current AND price_type='gross'").fetchall())
    assert at(r1["history_version_after"])["Aspgross"] == Decimal("100") and at(r2["history_version_after"])["Aspgross"] == Decimal("101")
    assert at(r3["history_version_after"])["Aspgross"] == Decimal("102")


def state(env, version=None):
    dt = DeltaTable(str(env[1]), version=version) if version is not None else DeltaTable(str(env[1]))
    return dt.to_pyarrow_table().to_pylist()


def test_initial_load_marks_everything_current(env):
    r = load(env, "v1", V1, T0)
    assert r["mode"] == "initial" and r["rows_inserted"] == 4
    assert all(x["is_current"] and x["effective_to"] is None for x in state(env))


def test_scd2_change_remove_add_unchanged(env):
    load(env, "v1", V1, T0)
    v2 = [("Asp", "111", None, "gross", 100),               # unchanged
          ("Asp", "111", "A", "negotiated", 90),            # changed 80 -> 90
          ("Dnt", "444", "A", "negotiated", 70)]            # added ; Bnd + Cst removed
    r = load(env, "v2", v2, T0 + timedelta(days=30))
    assert (r["rows_closed"], r["rows_inserted"], r["rows_unchanged"]) == (3, 2, 1)
    rows = state(env)
    cur = {(x["description"], x["price_type"]): x["amount"] for x in rows if x["is_current"]}
    assert cur == {("Asp", "gross"): Decimal("100"), ("Asp", "negotiated"): Decimal("90"), ("Dnt", "negotiated"): Decimal("70")}
    closed = {(x["description"], x["price_type"]): x for x in rows if not x["is_current"]}
    assert closed[("Asp", "negotiated")]["change_reason"] == "changed" and closed[("Asp", "negotiated")]["amount"] == Decimal("80")
    assert closed[("Bnd", "negotiated")]["change_reason"] == "removed" and closed[("Cst", "cash")]["change_reason"] == "removed"
    assert all(x["effective_to"] == T0 + timedelta(days=30) and x["closed_by_source_sha256"] == "v2" for x in closed.values())


def test_delta_time_travel_returns_exact_old_state(env):
    r1 = load(env, "v1", V1, T0)
    before = sorted((x["row_id"], x["is_current"], x["amount"]) for x in state(env))
    load(env, "v2", [("Asp", "111", None, "gross", 101)], T0 + timedelta(days=1))
    assert sorted((x["row_id"], x["is_current"], x["amount"]) for x in state(env, r1["history_version_after"])) == before
    assert sorted((x["row_id"], x["is_current"], x["amount"]) for x in state(env)) != before


def test_scd_as_of_timestamp_matches_delta_version(env):
    r1 = load(env, "v1", V1, T0)
    load(env, "v2", [("Asp", "111", None, "gross", 101)], T0 + timedelta(days=1))
    asof = {x["row_id"] for x in state(env) if x["effective_from"] <= T0 + timedelta(hours=1) and
            (x["effective_to"] is None or x["effective_to"] > T0 + timedelta(hours=1))}
    assert asof == {x["row_id"] for x in state(env, r1["history_version_after"]) if x["is_current"]}


def test_reload_same_version_is_skipped_and_identical_snapshot_is_noop(env):
    load(env, "v1", V1, T0)
    assert load(env, "v1", V1, T0)["mode"] == "skipped_already_loaded"
    v_before = DeltaTable(str(env[1])).version()
    r = load(env, "v1b", V1, T0 + timedelta(days=1))          # different file hash, identical content
    assert r["mode"] == "noop" and DeltaTable(str(env[1])).version() == v_before


def test_same_key_different_amounts_are_both_kept(env):
    r = load(env, "v1", [("Asp", "111", "A", "negotiated", 80), ("Asp", "111", "A", "negotiated", 95), ("Asp", "111", "A", "negotiated", 95)], T0)
    assert r["initial" if False else "rows_inserted"] == 2 and r["stage"]["rows_with_key_conflict_dup_seq_gt0"] == 1
    assert sorted(x["amount"] for x in state(env)) == [Decimal("80"), Decimal("95")]
