"""Streaming parsers: tall CSV, wide CSV, JSON -> canonical dict rows and Reject records.

Each parser is a generator of Reject | dict and updates `Stats`. Nothing is dropped silently: every
unusable row or price cell yields a Reject with a reason. Blank cells are not prices and are not rejects.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterator

import ijson

from pricecheck.silver.contract import Contract, split_wide_header
from pricecheck.silver.model import Reject, parse_amount, pick_codes

GENERIC_TALL = {"gross": "standard_charge|gross", "cash": "standard_charge|discounted_cash",
                "min": "standard_charge|min", "max": "standard_charge|max"}


@dataclass
class Stats:
    rows_in: int = 0
    non_dollar_negotiated: int = 0     # percentage/algorithm-only cells: real data, no dollar amount
    ignored_payer_cells: int = 0       # estimated_amount / percentiles / counts etc. (not in the 5 price types)
    extra: dict = field(default_factory=dict)


def _row(hospital, sha, n, desc, code, typ, alts, setting, bc, payer, plan, ptype, amount, meth, mods, ver, cver):
    return {"hospital_slug": hospital, "source_sha256": sha, "source_row": n, "description": desc, "code": code,
            "code_type": typ, "alt_codes": alts, "setting": setting, "billing_class": bc, "payer": payer, "plan": plan,
            "price_type": ptype, "amount": amount, "methodology": meth, "modifiers": mods,
            "template_version": ver, "contract_version": cver}


def _enum(value: str | None, allowed: set[str]) -> tuple[str | None, bool]:
    """(normalised, ok). Blank -> (None, True): absent is a contract-column question, not a row error."""
    v = (value or "").strip().lower()
    if not v:
        return None, True
    return v, v in allowed


class Ctx:
    def __init__(self, con: Contract, sha: str, version: str | None):
        self.con, self.sha, self.ver, self.stats = con, sha, version, Stats()
        self.max = Decimal(con.amount_max)

    def item(self, n, desc, pairs, setting, bc):
        """Validate item-level fields. Returns (base tuple) or a Reject."""
        if not (desc or "").strip():
            return Reject(n, "row", "missing_description")
        code, typ, alts = pick_codes(pairs)
        if code is None:
            return Reject(n, "row", "no_code", raw=desc[:80])
        s, ok = _enum(setting, set(self.con.allowed_settings))
        if not ok:
            return Reject(n, "row", "invalid_setting", "setting", str(setting)[:40])
        b, ok = _enum(bc, set(self.con.allowed_billing_classes))
        if not ok:
            return Reject(n, "row", "invalid_billing_class", "billing_class", str(bc)[:40])
        return desc.strip(), code, typ, alts, s, b

    def price(self, n, base, payer, plan, ptype, raw, field_name, meth="", mods=""):
        amount, reason = parse_amount(raw, self.max)
        if reason:
            return Reject(n, "price", reason, field_name, str(raw)[:40])
        if amount is None:
            return None
        desc, code, typ, alts, s, b = base
        return _row(self.con.source, self.sha, n, desc, code, typ, alts, s, b, payer, plan, ptype, amount,
                    meth or None, mods or None, self.ver, self.con.contract_version)


def _text(stream):
    return io.TextIOWrapper(stream, encoding="utf-8-sig", errors="cp1252_fallback", newline="")


def parse_tall(stream, ctx: Ctx) -> Iterator[Reject | dict]:
    r = csv.reader(_text(stream))
    next(r); next(r)
    cols = next(r)
    idx = {c: i for i, c in enumerate(cols)}
    n_codes = [k for k in range(1, 10) if f"code|{k}" in idx]
    for n, row in enumerate(r, start=1):
        ctx.stats.rows_in += 1
        if len(row) != len(cols):
            yield Reject(n, "row", "ragged_row", raw=",".join(row)[:80])
            continue
        g = lambda c: row[idx[c]].strip() if c in idx else ""  # noqa: E731
        base = ctx.item(n, g("description"), [(g(f"code|{k}"), g(f"code|{k}|type")) for k in n_codes],
                        g("setting"), g("billing_class"))
        if isinstance(base, Reject):
            yield base
            continue
        mods = g("modifiers")
        # Generic prices are emitted on EVERY row. They repeat across payer rows (exact duplicates are collapsed in the
        # history staging step), but rows for one code can carry *different* generic prices (e.g. one HCPCS drug code
        # listed per NDC with a different gross price), so deduplicating here by "same item key" silently lost data.
        for ptype, col in GENERIC_TALL.items():
            out = ctx.price(n, base, None, None, ptype, g(col), col, mods=mods)
            if out is not None:
                yield out
        payer = g("payer_name")
        if payer:
            out = ctx.price(n, base, payer, g("plan_name") or None, "negotiated", g("standard_charge|negotiated_dollar"),
                            "standard_charge|negotiated_dollar", g("standard_charge|methodology"), mods)
            if out is not None:
                yield out
            elif g("standard_charge|negotiated_percentage") or g("standard_charge|negotiated_algorithm"):
                ctx.stats.non_dollar_negotiated += 1


def parse_wide(stream, ctx: Ctx) -> Iterator[Reject | dict]:
    r = csv.reader(_text(stream))
    next(r); next(r)
    cols = next(r)
    idx = {c: i for i, c in enumerate(cols)}
    n_codes = [k for k in range(1, 10) if f"code|{k}" in idx]
    groups: dict[tuple[str, str], dict[str, int]] = {}
    ignored = 0
    for i, c in enumerate(cols):
        sp = split_wide_header(c)
        if sp is None:
            continue
        grp, payer, plan, suf = sp
        if grp == "standard_charge" and suf in ("negotiated_dollar", "methodology"):
            groups.setdefault((payer, plan), {})[suf] = i
        else:
            ignored += 1
    dollar_cols = [(pl, d["negotiated_dollar"], d.get("methodology")) for pl, d in groups.items() if "negotiated_dollar" in d]
    ctx.stats.extra["payer_plan_columns"] = len(dollar_cols)
    ctx.stats.extra["ignored_payer_columns"] = ignored
    for n, row in enumerate(r, start=1):
        ctx.stats.rows_in += 1
        if len(row) != len(cols):
            yield Reject(n, "row", "ragged_row", raw=",".join(row)[:80])
            continue
        g = lambda c: row[idx[c]].strip() if c in idx else ""  # noqa: E731
        base = ctx.item(n, g("description"), [(g(f"code|{k}"), g(f"code|{k}|type")) for k in n_codes],
                        g("setting"), g("billing_class"))
        if isinstance(base, Reject):
            yield base
            continue
        mods = g("modifiers")
        for ptype, col in GENERIC_TALL.items():
            out = ctx.price(n, base, None, None, ptype, g(col), col, mods=mods)
            if out is not None:
                yield out
        for (payer, plan), di, mi in dollar_cols:
            cell = row[di]
            if not cell.strip():
                continue
            out = ctx.price(n, base, payer, plan or None, "negotiated", cell, cols[di], row[mi] if mi is not None else "", mods)
            if out is not None:
                yield out


def parse_json(stream, ctx: Ctx) -> Iterator[Reject | dict]:
    if not hasattr(stream, "peek"):
        stream = io.BufferedReader(stream)
    if stream.peek(3)[:3] == b"\xef\xbb\xbf":   # UTF-8 BOM: valid text, but the JSON parser rejects it
        stream.read(3)
    for n, it in enumerate(ijson.items(stream, "standard_charge_information.item", use_float=False), start=1):
        ctx.stats.rows_in += 1
        pairs = [(ci.get("code", ""), ci.get("type", "")) for ci in it.get("code_information") or []]
        item_bc = it.get("billing_class")
        for sc in it.get("standard_charges") or []:
            base = ctx.item(n, it.get("description"), pairs, sc.get("setting"), sc.get("billing_class") or item_bc)
            if isinstance(base, Reject):
                yield base
                continue
            for ptype, key in (("gross", "gross_charge"), ("cash", "discounted_cash"), ("min", "minimum"), ("max", "maximum")):
                out = ctx.price(n, base, None, None, ptype, sc.get(key), key)
                if out is not None:
                    yield out
            for p in sc.get("payers_information") or []:
                out = ctx.price(n, base, p.get("payer_name"), p.get("plan_name"), "negotiated",
                                p.get("standard_charge_dollar"), "standard_charge_dollar", p.get("methodology") or "")
                if out is not None:
                    yield out
                elif p.get("standard_charge_percentage") or p.get("standard_charge_algorithm"):
                    ctx.stats.non_dollar_negotiated += 1


PARSERS = {"csv_tall": parse_tall, "csv_wide": parse_wide, "json": parse_json}
