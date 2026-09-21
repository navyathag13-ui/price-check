"""Anomaly detectors: fixed statistical rules + per-price-type Isolation Forest.

Thresholds are set BEFORE looking at what they flag and are not tuned on the injected-anomaly test:
  R1_robust_z       |robust z| >= 5 against the cross-hospital peer group
  R2_neg_gt_gross   negotiated > 1.10 x the item's own median gross charge
  R3_out_of_range   negotiated < 0.90 x item min, or > 1.10 x item max (when the item publishes min/max)
  R4_cash_gt_gross  cash > 1.10 x the item's own median gross charge
  R5_placeholder    amount >= 99,999 whose digits start with 5+ nines (e.g. 999999.99)
Isolation Forest: trained on a random 400k-row sample per price type (negotiated, cash); flag = score in the lowest
0.5% of the *training sample* (contamination is a design parameter for how many rows a reviewer will see, not a
claim that 0.5% of prices are wrong). Gross prices are rule-only (one usable feature makes a forest pointless).
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data/anomaly"
Z_THRESHOLD, RATIO = 5.0, 1.10
IF_TYPES = ("negotiated", "cash")
CONTAMINATION = 0.005
SEED = 20260921


def rules(df: pd.DataFrame) -> pd.DataFrame:
    neg, cash = df.price_type.eq("negotiated"), df.price_type.eq("cash")
    r = pd.DataFrame(index=df.index)
    r["R1_robust_z"] = df.robust_z.abs() >= Z_THRESHOLD
    r["R2_neg_gt_gross"] = neg & df.item_gross.notna() & (df.amount > RATIO * df.item_gross)
    r["R3_out_of_range"] = neg & ((df.item_min.notna() & (df.amount < 0.9 * df.item_min)) | (df.item_max.notna() & (df.amount > 1.1 * df.item_max)))
    r["R4_cash_gt_gross"] = cash & df.item_gross.notna() & (df.amount > RATIO * df.item_gross)
    digits = df.amount.round(2).map(lambda a: f"{a:.2f}")
    r["R5_placeholder"] = (df.amount >= 99999) & digits.str.match(r"^9{5,}")
    return r


def feature_matrix(df: pd.DataFrame, ptype: str) -> np.ndarray:
    def lr(col):
        v = np.log(df.amount / df[col]).where(df[col].notna() & (df[col] > 0))
        return v.fillna(0.0).to_numpy()
    cols = [df.robust_z.to_numpy(), lr("item_gross"), df.item_gross.notna().to_numpy().astype(float)]
    if ptype == "negotiated":
        cols += [lr("item_min"), lr("item_max")]
    return np.column_stack(cols)


def fit(features_path: Path = OUT / "features.parquet", n_train: int = 400_000) -> dict:
    models, thresholds = {}, {}
    for t in IF_TYPES:
        df = pd.read_parquet(features_path, filters=[("price_type", "=", t)],
                             columns=["row_id", "amount", "price_type", "robust_z", "item_gross", "item_min", "item_max"])
        tr = df.sample(min(n_train, len(df)), random_state=SEED)
        X = feature_matrix(tr, t)
        m = IsolationForest(n_estimators=200, max_samples=512, random_state=SEED, n_jobs=-1).fit(X)
        thresholds[t] = float(np.quantile(m.decision_function(X), CONTAMINATION))
        models[t] = m
        tr[["row_id"]].to_parquet(OUT / f"if_train_ids_{t}.parquet")
    joblib.dump({"models": models, "thresholds": thresholds}, OUT / "isolation_forest.joblib")
    (OUT / "if_thresholds.json").write_text(json.dumps({"thresholds": thresholds, "contamination": CONTAMINATION, "seed": SEED}, indent=2))
    return thresholds


def score_frame(df: pd.DataFrame, bundle: dict) -> pd.DataFrame:
    out = rules(df)
    out["if_score"] = np.nan
    out["IF_flag"] = False
    for t in IF_TYPES:
        idx = df.index[df.price_type.eq(t)]
        if len(idx):
            s = bundle["models"][t].decision_function(feature_matrix(df.loc[idx], t))
            out.loc[idx, "if_score"] = s
            out.loc[idx, "IF_flag"] = s < bundle["thresholds"][t]
    rule_cols = [c for c in out.columns if c.startswith("R")]
    out["any_rule"] = out[rule_cols].any(axis=1)
    out["any_flag"] = out.any_rule | out.IF_flag
    return out


def run_all(features_path: Path = OUT / "features.parquet", chunk: int = 2_000_000) -> dict:
    import pyarrow.dataset as pds
    bundle = joblib.load(OUT / "isolation_forest.joblib")
    ds = pds.dataset(features_path)
    parts, cols = [], ["row_id", "hospital_slug", "code", "price_type", "amount", "robust_z", "item_gross", "item_cash", "item_min", "item_max"]
    for b in ds.to_batches(columns=cols, batch_size=chunk):
        df = b.to_pandas()
        s = score_frame(df, bundle)
        parts.append(pd.concat([df[["row_id", "hospital_slug", "code", "price_type"]], s], axis=1))
    flags = pd.concat(parts, ignore_index=True)
    flags.to_parquet(OUT / "flags.parquet", index=False)
    return {"rows_scored": len(flags), "flagged": int(flags.any_flag.sum())}


if __name__ == "__main__":
    import time
    t = time.monotonic(); th = fit(); print("IF thresholds", th, round(time.monotonic() - t, 1), "s")
    t = time.monotonic(); print(run_all(), round(time.monotonic() - t, 1), "s")
