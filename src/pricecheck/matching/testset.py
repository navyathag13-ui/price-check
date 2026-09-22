"""Stratified test (200) and dev (3,000) sets: hospital items with a standard code, label = the hospital's own code.

Test set is what gets reviewed by hand (label sanity); dev set is only used to calibrate tiering thresholds.
"""
import json

import pandas as pd

from pricecheck.matching.vocab import OUT

TEST_QUOTA = {"cpt_numeric": 80, "drug_J": 40, "device_or_other_hcpcs": 60, "ms_drg": 20}
DEV_QUOTA = {"cpt_numeric": 1200, "drug_J": 600, "device_or_other_hcpcs": 900, "ms_drg": 300}


def sample(items, quota, seed, exclude=frozenset()):
    parts = []
    for fam, n in quota.items():
        d = items[(items.family == fam) & (items.text.str.len() >= 8)]
        d = d[~d.set_index(["hospital_slug", "text"]).index.isin(exclude)].drop_duplicates(["hospital_slug", "text"])
        parts.append(d.sample(n, random_state=seed))
    return pd.concat(parts, ignore_index=True)


def annotate(df, vocab, bits):
    idx = vocab.groupby("code").mask.apply(list).to_dict()
    df["in_vocab"] = [any(m & ~bits[h] for m in idx.get(c, [])) for h, c in zip(df.hospital_slug, df.code)]
    return df


if __name__ == "__main__":
    items = pd.read_parquet(OUT / "items.parquet"); vocab = pd.read_parquet(OUT / "vocab.parquet"); bits = json.load(open(OUT / "hospital_bits.json"))
    test = annotate(sample(items, TEST_QUOTA, 11), vocab, bits)
    ex = set(zip(test.hospital_slug, test.text))
    dev = annotate(sample(items, DEV_QUOTA, 23, ex), vocab, bits)
    test.to_parquet(OUT / "test.parquet"); dev.to_parquet(OUT / "dev.parquet")
    for n, d in (("test", test), ("dev", dev)):
        print(n, len(d), "in-vocab (matchable) share:", round(d.in_vocab.mean(), 3), d.groupby("family").in_vocab.mean().round(3).to_dict())
