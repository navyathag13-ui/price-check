"""Build per-price features for anomaly detection from the CURRENT rows of the history table.

Peer group = (code, price_type, setting, billing_class) across hospitals, for CPT/HCPCS/MS-DRG codes, only where
>= MIN_HOSPITALS hospitals and >= MIN_ROWS rows exist. Robust z = (ln amount - group median) / max(1.4826*MAD, SCALE_FLOOR).
Item context (same hospital/code/description/setting/billing class): median gross and cash, median min and max.
Rows in groups too small to compare are NOT scored (recorded as a coverage limit, never silently treated as normal).
"""
from __future__ import annotations

from pathlib import Path

from pricecheck.history import delta_store as D

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data/anomaly"
MIN_HOSPITALS, MIN_ROWS, SCALE_FLOOR = 5, 30, 0.10
TYPES = ("negotiated", "cash", "gross")


def build(history: Path = ROOT / "data/delta/price_history", out: Path = OUT) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "data/tmp"; tmp.mkdir(exist_ok=True)
    con = D.duck()
    con.execute(f"SET memory_limit='11GB'; SET temp_directory='{tmp}'; SET preserve_insertion_order=false")
    src = f"delta_scan('{history}')"
    con.execute(f"""CREATE TEMP TABLE base AS
        SELECT row_id, hospital_slug, code, code_type, description, coalesce(setting,'na') AS setting,
               coalesce(billing_class,'na') AS billing_class, price_type, payer, plan, cast(amount as double) AS amount,
               ln(cast(amount as double)) AS ln_amt
        FROM {src} WHERE is_current AND price_type IN ('negotiated','cash','gross') AND code_type IN ('CPT','HCPCS','MS-DRG')""")
    con.execute("""CREATE TEMP TABLE gstat0 AS SELECT code, price_type, setting, billing_class, count(*) AS n,
        count(DISTINCT hospital_slug) AS n_hosp, median(ln_amt) AS med FROM base GROUP BY ALL""")
    con.execute(f"""CREATE TEMP TABLE gstat AS
        SELECT g.*, greatest(1.4826 * mad.mad, {SCALE_FLOOR}) AS scale FROM gstat0 g JOIN (
          SELECT b.code, b.price_type, b.setting, b.billing_class, median(abs(b.ln_amt - g0.med)) AS mad
          FROM base b JOIN gstat0 g0 USING (code, price_type, setting, billing_class) GROUP BY ALL) mad USING (code, price_type, setting, billing_class)
        WHERE g.n_hosp >= {MIN_HOSPITALS} AND g.n >= {MIN_ROWS}""")
    con.execute(f"COPY gstat TO '{out}/group_stats.parquet' (FORMAT parquet, COMPRESSION zstd)")
    con.execute(f"""CREATE TEMP TABLE ctx AS
        SELECT hospital_slug, code, description, coalesce(setting,'na') AS setting, coalesce(billing_class,'na') AS billing_class,
               median(cast(amount as double)) FILTER (price_type='gross') AS item_gross, median(cast(amount as double)) FILTER (price_type='cash') AS item_cash,
               median(cast(amount as double)) FILTER (price_type='min') AS item_min, median(cast(amount as double)) FILTER (price_type='max') AS item_max
        FROM {src} WHERE is_current AND code_type IN ('CPT','HCPCS','MS-DRG') GROUP BY ALL""")
    con.execute(f"""COPY (
        SELECT b.row_id, b.hospital_slug, b.code, b.code_type, b.description, b.setting, b.billing_class, b.price_type, b.payer, b.plan,
               b.amount, b.ln_amt, g.med AS peer_med, g.scale AS peer_scale, g.n AS peer_n, g.n_hosp AS peer_hosp,
               (b.ln_amt - g.med) / g.scale AS robust_z, c.item_gross, c.item_cash, c.item_min, c.item_max
        FROM base b JOIN gstat g USING (code, price_type, setting, billing_class)
        LEFT JOIN ctx c USING (hospital_slug, code, description, setting, billing_class)
    ) TO '{out}/features.parquet' (FORMAT parquet, COMPRESSION zstd)""")
    total = con.execute("SELECT price_type, count(*) FROM base GROUP BY 1 ORDER BY 1").fetchall()
    scored = con.execute(f"SELECT price_type, count(*) FROM read_parquet('{out}/features.parquet') GROUP BY 1 ORDER BY 1").fetchall()
    return {"candidate_rows": dict(total), "scored_rows": dict(scored)}


if __name__ == "__main__":
    import json
    import time
    t = time.monotonic(); r = build(); r["seconds"] = round(time.monotonic() - t, 1)
    r["coverage"] = {k: round(r["scored_rows"][k] / r["candidate_rows"][k], 4) for k in r["scored_rows"]}
    (OUT / "features_summary.json").write_text(json.dumps(r, indent=2)); print(json.dumps(r, indent=2))
