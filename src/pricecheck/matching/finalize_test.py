"""Merge the resumable LLM caches (test set, both modes) back into results_full_test.parquet."""
import json
import pandas as pd
from pricecheck.matching.vocab import OUT

df = pd.read_parquet(OUT / "results_ab_test.parquet")
for mode in ("candidates", "free"):
    cache = OUT / f"llm_test_{mode}.jsonl"
    recs = {json.loads(l)["idx"]: json.loads(l) for l in cache.read_text().splitlines()}
    r = pd.DataFrame(recs.values()).set_index("idx").sort_index().add_prefix(f"{mode[:4]}_")
    df = df.join(r)
    acc = (df[f"{mode[:4]}_llm_code"] == df.code).mean()
    print(mode, "n=", len(r), "acc=", round(float(acc), 3))
df.to_parquet(OUT / "results_full_test.parquet")
