"""Per-hospital data-quality score: completeness, validity, consistency, freshness (each 0..1) and their equal-weight mean.

Every component is a plain, inspectable ratio; the raw metrics are stored next to the scores. Equal weights and the
freshness window are judgment calls, not empirically validated (see DECISIONS.md ADR-014).
  completeness  mean over items of has_gross, has_cash, has_min, has_max, has_negotiated (an item = hospital+code+description+setting+billing class)
  validity      mean of (1 - parse reject rate), (1 - sentinel rate), (share of items carrying a standard code: CPT/HCPCS/MS-DRG/APR-DRG/ICD-10-PCS/NDC)
  consistency   mean of (1 - violation rate) for: negotiated <= 1.10 x gross; negotiated within [0.9 x min, 1.1 x max];
                cash <= 1.10 x gross; min <= max. Each rate is over rows/items where the check can be evaluated.
  freshness     mean of max(0, 1 - days_since_last_update/365) and 1 if the template version is current else 0
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pyarrow as pa
from deltalake import write_deltalake

from pricecheck.history import delta_store as D

ROOT = Path(__file__).resolve().parents[3]
STD = "('CPT','HCPCS','MS-DRG','APR-DRG','ICD-10-PCS','NDC')"
CURRENT_TEMPLATE = "3.0.0"


def parse_date(s: str | None) -> date | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime((s or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def compute(as_of: date) -> list[dict]:
    p = ROOT / "data/delta/price_history"
    con = D.duck()
    con.execute(f"SET memory_limit='11GB'; SET temp_directory='{ROOT / 'data/tmp'}'; SET preserve_insertion_order=false")
    con.execute(f"""CREATE TEMP TABLE item AS SELECT hospital_slug, code, description, coalesce(setting,'na') s, coalesce(billing_class,'na') b,
        any_value(code_type) code_type,
        bool_or(price_type='gross') has_gross, bool_or(price_type='cash') has_cash, bool_or(price_type='min') has_min,
        bool_or(price_type='max') has_max, bool_or(price_type='negotiated') has_neg,
        median(cast(amount as double)) FILTER (price_type='gross') gross, median(cast(amount as double)) FILTER (price_type='min') mn,
        median(cast(amount as double)) FILTER (price_type='max') mx
        FROM delta_scan('{p}') WHERE is_current GROUP BY hospital_slug, code, description, coalesce(setting,'na'), coalesce(billing_class,'na')""")
    comp = {r[0]: r[1:] for r in con.execute(f"""SELECT hospital_slug, count(*), avg(has_gross::int), avg(has_cash::int), avg(has_min::int), avg(has_max::int),
        avg(has_neg::int), avg((code_type IN {STD})::int), avg((mn > mx)::int) FILTER (mn IS NOT NULL AND mx IS NOT NULL) FROM item GROUP BY 1""").fetchall()}
    rows = {r[0]: r[1:] for r in con.execute(f"""SELECT r.hospital_slug, count(*),
        avg((r.amount > 1.10*i.gross)::int) FILTER (r.price_type='negotiated' AND i.gross IS NOT NULL),
        avg((r.amount < 0.9*i.mn OR r.amount > 1.1*i.mx)::int) FILTER (r.price_type='negotiated' AND (i.mn IS NOT NULL OR i.mx IS NOT NULL)),
        avg((r.amount > 1.10*i.gross)::int) FILTER (r.price_type='cash' AND i.gross IS NOT NULL),
        avg(((r.amount = 1 AND r.price_type IN ('negotiated','cash') AND i.gross >= 100) OR (r.amount >= 99999 AND regexp_matches(cast(r.amount as varchar), '^9{{5,}}')))::int)
        FROM delta_scan('{p}') r JOIN item i ON i.hospital_slug=r.hospital_slug AND i.code=r.code AND i.description=r.description
          AND i.s=coalesce(r.setting,'na') AND i.b=coalesce(r.billing_class,'na')
        WHERE r.is_current GROUP BY 1""").fetchall()}
    runlog = {}
    for l in (ROOT / "data/silver/run_log.jsonl").read_text().splitlines():
        r = json.loads(l); runlog[r["slug"]] = r
    prof = {}
    for l in (ROOT / "data/bronze/profile.jsonl").read_text().splitlines():
        r = json.loads(l); prof[r["slug"]] = r
    out = []
    for slug in sorted(comp):
        n_items, g, c, mn, mx, ng, std, minmax = comp[slug]
        n_rows, v_neg_gross, v_range, v_cash, sentinel = rows[slug]
        rl = runlog[slug]; rej = rl["rejects"] / max(rl["rows_out"] + rl["rejects"], 1)
        upd = parse_date(prof[slug].get("last_updated_on")); days = (as_of - upd).days if upd else None
        ver_ok = 1.0 if prof[slug].get("declared_version") == CURRENT_TEMPLATE else 0.0
        z = lambda x: 0.0 if x is None else float(x)  # noqa: E731
        completeness = (g + c + mn + mx + ng) / 5
        validity = ((1 - rej) + (1 - z(sentinel)) + std) / 3
        cons_parts = [1 - z(v_neg_gross), 1 - z(v_range), 1 - z(v_cash), 1 - z(minmax)]
        consistency = sum(cons_parts) / 4
        fresh = ((max(0.0, 1 - days / 365) if days is not None else 0.0) + ver_ok) / 2
        out.append({"hospital_slug": slug, "source_sha256": rl["sha256"], "as_of": as_of, "items": n_items, "price_rows": n_rows,
                    "completeness": round(completeness, 4), "validity": round(validity, 4), "consistency": round(consistency, 4),
                    "freshness": round(fresh, 4), "quality_score": round((completeness + validity + consistency + fresh) / 4 * 100, 1),
                    "m_has_gross": round(g, 4), "m_has_cash": round(c, 4), "m_has_min": round(mn, 4), "m_has_max": round(mx, 4),
                    "m_has_negotiated": round(ng, 4), "m_reject_rate": round(rej, 6), "m_sentinel_rate": round(z(sentinel), 6),
                    "m_standard_code_share": round(std, 4), "m_neg_gt_gross_rate": round(z(v_neg_gross), 4),
                    "m_neg_out_of_minmax_rate": round(z(v_range), 4), "m_cash_gt_gross_rate": round(z(v_cash), 4),
                    "m_min_gt_max_rate": round(z(minmax), 4), "m_days_since_update": days, "m_template_current": ver_ok})
    return out


def save(rows: list[dict]) -> None:
    write_deltalake(str(ROOT / "data/delta/quality_scores"), pa.Table.from_pylist(rows), mode="append")


if __name__ == "__main__":
    import pandas as pd
    rows = compute(date(2026, 9, 21)); save(rows)
    df = pd.DataFrame(rows).sort_values("quality_score")
    pd.set_option("display.width", 220)
    print(df[["hospital_slug", "quality_score", "completeness", "validity", "consistency", "freshness"]].to_string(index=False))
    df.to_csv(ROOT / "docs/quality_scores.csv", index=False)
