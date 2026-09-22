"""Run the three matchers on the test (200) and dev (3,000) sets. Stages cache to data/matching/*.parquet.
usage: python -m pricecheck.matching.evaluate ab | llm-test | llm-dev"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from pricecheck.matching.matchers import CATCH_ALL, EmbeddingMatcher, FuzzyMatcher, Vocab
from pricecheck.matching.vocab import OUT

SUSPECT_TEST_IDX = {67, 117, 149}   # label-noise suspects found in the hand review (docs/phase5_report.md)


def stage_ab():
    V = Vocab(); F = FuzzyMatcher(V); E = EmbeddingMatcher(V)
    for name in ("test", "dev"):
        df = pd.read_parquet(OUT / f"{name}.parquet").reset_index(drop=True)
        rows = []
        vecs = E.encode(df.text.tolist())                     # batch (throughput); latency measured per item below on test
        for i, r in df.iterrows():
            t = time.perf_counter(); a_code, a_score, a_m = F.match(r.text, r.hospital_slug); a_ms = (time.perf_counter() - t) * 1000
            t = time.perf_counter()
            ranked = E.match_vec(vecs[i], r.hospital_slug)
            b_ms_search = (time.perf_counter() - t) * 1000
            b_ms = None
            if name == "test":                                # honest single-item latency = encode + search
                t = time.perf_counter(); v1 = E.encode([r.text])[0]; E.match_vec(v1, r.hospital_slug); b_ms = (time.perf_counter() - t) * 1000
            rows.append({"a_code": a_code, "a_score": a_score, "a_method": a_m, "a_ms": a_ms,
                         "b_code": ranked[0][0] if ranked else None, "b_sim": ranked[0][1] if ranked else 0.0, "b_ms": b_ms,
                         "b_search_ms": b_ms_search, "b_top10": [c for c, _ in ranked]})
        out = pd.concat([df, pd.DataFrame(rows)], axis=1)
        out["catch_all"] = out.code.isin(CATCH_ALL)
        if name == "test":
            out["suspect"] = out.index.isin(SUSPECT_TEST_IDX)
        out.to_parquet(OUT / f"results_ab_{name}.parquet")
        print(name, "done", len(out), "| fuzzy acc", round((out.a_code == out.code).mean(), 3), "| embed acc", round((out.b_code == out.code).mean(), 3))


def _llm_run(df, mode, V, workers=3, tag="run"):
    """Resumable: each finished call is appended to data/matching/llm_<tag>_<mode>.jsonl and skipped on restart."""
    import json, threading
    from pricecheck.matching.llm import LLM
    llm = LLM(); ref = V.v.groupby("code").text.first().to_dict()
    cache = OUT / f"llm_{tag}_{mode}.jsonl"; lock = threading.Lock()
    done = {json.loads(l)["idx"]: json.loads(l) for l in cache.read_text().splitlines()} if cache.exists() else {}

    def one(i):
        if i in done:
            return done[i]
        r = df.loc[i]
        cands = None if mode == "free" else [(c, ref.get(c, "")) for c in r.b_top10]
        code, conf, dt, pt, ct = llm.choose(r.description, cands)
        rec = {"idx": int(i), "llm_code": code, "llm_conf": conf, "llm_s": dt, "prompt_tokens": pt, "completion_tokens": ct}
        with lock:
            with cache.open("a") as f:
                f.write(json.dumps(rec) + "\n")
        return rec
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, df.index))
    return pd.DataFrame(res).set_index("idx")


def stage_llm_test():
    V = Vocab(); df = pd.read_parquet(OUT / "results_ab_test.parquet")
    for mode in ("candidates", "free"):
        r = _llm_run(df, mode, V, tag="test").add_prefix(f"{mode[:4]}_")
        df = df.join(r)
        print(mode, "acc", round((df[f"{mode[:4]}_llm_code"] == df.code).mean(), 3))
    df.to_parquet(OUT / "results_full_test.parquet")


def stage_llm_dev(n=300, seed=5):
    """LLM (candidates mode) on a random sample of dev items that neither fuzzy>=0.9 nor embedding>=0.9 would resolve."""
    V = Vocab(); df = pd.read_parquet(OUT / "results_ab_dev.parquet")
    hard = df[(df.a_score < 0.9) & (df.b_sim < 0.9)].sample(n, random_state=seed)
    r = _llm_run(hard, "candidates", V, tag="devhard").add_prefix("cand_")
    hard.join(r).to_parquet(OUT / "results_llm_dev_hard.parquet"); print("dev hard subset acc", round((hard.join(r).cand_llm_code == hard.code).mean(), 3), "of pool", int(((df.a_score < 0.9) & (df.b_sim < 0.9)).sum()))


if __name__ == "__main__":
    {"ab": stage_ab, "llm-test": stage_llm_test, "llm-dev": stage_llm_dev}[sys.argv[1]]()
