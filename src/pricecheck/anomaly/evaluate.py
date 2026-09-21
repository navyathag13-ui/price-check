"""Recall on INJECTED synthetic anomalies, at thresholds fixed before this test (no tuning on it).

Clean rows are sampled from the scored population, excluding the Isolation Forest's training rows. Each sampled row
receives exactly one corruption, features are recomputed against the ORIGINAL peer statistics, and the same fixed
rules + trained forest are applied. Context-dependent corruptions are only applied to rows that have that context.
Caveat (also in DECISIONS.md): recall on corruptions I invented measures whether the detectors see the errors I thought
of; it says nothing about errors I did not think of.
"""
from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd

from pricecheck.anomaly import detect as DT

OUT = DT.OUT
SEED = 7
PER_TYPE = 6000
COLS = ["row_id", "hospital_slug", "code", "price_type", "amount", "ln_amt", "peer_med", "peer_scale", "robust_z",
        "item_gross", "item_cash", "item_min", "item_max"]


def main() -> dict:
    rng = np.random.default_rng(SEED)
    bundle = joblib.load(OUT / "isolation_forest.joblib")
    train_ids = set(pd.concat([pd.read_parquet(OUT / f"if_train_ids_{t}.parquet").row_id for t in DT.IF_TYPES]))
    df = pd.read_parquet(OUT / "features.parquet", columns=COLS, filters=[("price_type", "in", list(DT.IF_TYPES))])
    df = df[~df.row_id.isin(train_ids)]
    # sample negotiated and cash rows in proportion 4:1 to what the detectors will really see
    kinds = {
        "x10": ("all", lambda d: d.amount * 10), "x100": ("all", lambda d: d.amount * 100),
        "div10": ("all", lambda d: d.amount / 10), "div100": ("all", lambda d: d.amount / 100),
        "placeholder_999999.99": ("all", lambda d: pd.Series(999999.99, index=d.index)),
        "item_consistent_x10": ("all", None), "item_consistent_x100": ("all", None),
        "negotiated_3x_gross": ("has_gross_neg", lambda d: d.item_gross * 3),
        "negotiated_half_of_min": ("has_min_neg", lambda d: d.item_min * 0.5),
    }
    parts = []
    for k, (need, fn) in kinds.items():
        pool = df
        if need == "has_gross_neg":
            pool = df[df.price_type.eq("negotiated") & df.item_gross.notna() & (df.item_gross > 0)]
        elif need == "has_min_neg":
            pool = df[df.price_type.eq("negotiated") & df.item_min.notna() & (df.item_min > 0)]
        s = pool.sample(min(PER_TYPE, len(pool)), random_state=int(rng.integers(1 << 30))).copy()
        s["inj_type"] = k
        s["clean_amount"] = s.amount
        if k.startswith("item_consistent"):       # whole item mis-scaled: amount AND its own gross/cash/min/max
            f = 10.0 if k.endswith("x10") else 100.0
            s["amount"] = s.amount * f
            for c in ("item_gross", "item_cash", "item_min", "item_max"):
                s[c] = s[c] * f
        else:
            s["amount"] = fn(s).astype(float)
        s["ln_amt"] = np.log(s.amount)
        s["robust_z"] = (s.ln_amt - s.peer_med) / s.peer_scale
        parts.append(s)
    inj = pd.concat(parts, ignore_index=True)
    sc = DT.score_frame(inj, bundle)
    res = pd.concat([inj[["inj_type", "price_type"]], sc[["any_rule", "IF_flag", "any_flag", "R1_robust_z"]]], axis=1)
    res["has_ctx"] = (inj.item_gross.notna() | inj.item_min.notna() | inj.item_max.notna()).to_numpy()
    by = res.groupby("inj_type").agg(n=("any_flag", "size"), rules=("any_rule", "mean"), isolation_forest=("IF_flag", "mean"),
                                     combined=("any_flag", "mean"))
    ctx_split = {}
    for k in ("x10", "x100", "div10", "div100", "item_consistent_x10", "item_consistent_x100"):
        for name, m in (("with_item_context", res.has_ctx), ("no_item_context", ~res.has_ctx)):
            r = res[(res.inj_type == k) & m]
            ctx_split[f"{k}/{name}"] = {"n": int(len(r)), "peer_only_R1": round(float(r.R1_robust_z.mean()), 4) if len(r) else None,
                                        "rules": round(float(r.any_rule.mean()), 4) if len(r) else None,
                                        "isolation_forest": round(float(r.IF_flag.mean()), 4) if len(r) else None,
                                        "combined": round(float(r.any_flag.mean()), 4) if len(r) else None}
    # natural (uninjected) flag rate on comparable clean rows, for context on false alarms
    clean = df.sample(200_000, random_state=SEED).copy()
    csc = DT.score_frame(clean, bundle)
    out = {"per_type": {k: {c: round(float(v), 4) for c, v in r.items()} for k, r in by.iterrows()},
           "overall_recall": {"rules": round(float(res.any_rule.mean()), 4), "isolation_forest": round(float(res.IF_flag.mean()), 4),
                              "combined": round(float(res.any_flag.mean()), 4)},
           "n_injected": int(len(res)), "recall_by_item_context": ctx_split, "natural_flag_rate_on_clean_sample": {
               "rules": round(float(csc.any_rule.mean()), 4), "isolation_forest": round(float(csc.IF_flag.mean()), 4),
               "combined": round(float(csc.any_flag.mean()), 4), "n": len(clean)},
           "peer_scale_median_by_type": {t: round(float(df[df.price_type.eq(t)].peer_scale.median()), 3) for t in DT.IF_TYPES}}
    (OUT / "injection_eval.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
