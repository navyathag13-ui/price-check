"""Tiered matching: cheapest method that is good enough first. Thresholds are calibrated on DEV only (target dev precision
>= TARGET per tier), then applied once to TEST. Compares two orders of the two non-LLM tiers."""
from __future__ import annotations

import pandas as pd

TARGET = 0.95
GRID = [0.7, 0.75, 0.8, 0.85, 0.9, 0.92, 0.95, 0.97, 1.0]
# ESTIMATE ONLY: base gpt-4.1-mini meters were not retrievable; these are the public gpt-4.1-mini *fine-tuned* global rates
# ($0.40 / $1.60 per 1M tokens) used as a stand-in. Real billed cost = Azure Cost Management.
PRICE_IN_PER_TOKEN, PRICE_OUT_PER_TOKEN = 0.40e-6, 1.60e-6


def pick(df, code_col, score_col):
    """Lowest threshold whose precision on df is >= TARGET (max coverage subject to precision)."""
    for th in GRID:
        m = df[score_col] >= th
        if m.sum() >= 30 and (df[m][code_col] == df[m].code).mean() >= TARGET:
            return th
    return None


def calibrate(dev: pd.DataFrame, order: str) -> dict:
    stages = [("exact_fuzzy", "a_code", "a_score"), ("embedding", "b_code", "b_sim")]
    if order == "embedding_first":
        stages = stages[::-1]
    th, rest = {}, dev
    for name, c, s in stages:
        t = pick(rest, c, s); th[name] = t
        if t is not None:
            rest = rest[rest[s] < t]
    return {"order": [s[0] for s in stages], "thresholds": th}


def apply(df: pd.DataFrame, cal: dict, llm_col: str | None) -> pd.DataFrame:
    stages = {"exact_fuzzy": ("a_code", "a_score"), "embedding": ("b_code", "b_sim")}
    out = df.copy(); out["tier"] = None; out["pred"] = None
    for name in cal["order"]:
        t = cal["thresholds"][name]
        if t is None:
            continue
        c, s = stages[name]
        m = out.tier.isna() & (out[s] >= t)
        out.loc[m, "tier"] = name; out.loc[m, "pred"] = out.loc[m, c]
    if llm_col:
        conf = llm_col.replace("llm_code", "llm_conf")
        m = out.tier.isna() & out[llm_col].notna() & (out[conf] == "high")
        out.loc[m, "tier"] = "llm"; out.loc[m, "pred"] = out.loc[m, llm_col]
    out["tier"] = out.tier.fillna("human_review")
    return out


def summarize(t: pd.DataFrame) -> dict:
    def sub(d):
        a = d[d.tier != "human_review"]
        return {"n": int(len(d)), "answered": int(len(a)), "precision": round(float((a.pred == a.code).mean()), 3) if len(a) else None,
                "recall": round(float((a.pred == a.code).sum() / len(d)), 3) if len(d) else None}
    per_tier = {k: {"items": int(len(g)), "precision": round(float((g.pred == g.code).mean()), 3) if k != "human_review" else None}
                for k, g in t.groupby("tier")}
    return {"all": sub(t), "excl_suspect": sub(t[~t.suspect]), "specific_codes": sub(t[~t.suspect & ~t.catch_all]),
            "catch_all_codes": sub(t[t.catch_all]), "per_tier": per_tier}
