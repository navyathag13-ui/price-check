"""Method (a): rules + fuzzy string matching; method (b): embedding search with a FAISS index. Both are leave-one-hospital-out."""
from __future__ import annotations

import collections
import json
import time
from pathlib import Path

import faiss
import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from pricecheck.matching.vocab import OUT

CATCH_ALL = {"J3490", "J8499", "J9999", "J7999", "C1713", "C1776", "C1769", "C1725", "C1876", "C1889", "C1887", "C1767", "C1781",
             "C1789", "C1768", "C2617", "V2632", "V2787", "V2788", "A4649"}
MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class Vocab:
    def __init__(self):
        self.v = pd.read_parquet(OUT / "vocab.parquet")
        self.bits = json.load(open(OUT / "hospital_bits.json"))
        self.texts = self.v.text.tolist(); self.codes = self.v.code.tolist(); self.masks = self.v["mask"].to_numpy(dtype=np.int64)
        self.n_hosp = self.v.n_hosp.tolist()

    def allowed(self, idx, hospital: str) -> bool:
        return bool(self.masks[idx] & ~self.bits.get(hospital, 0))


class FuzzyMatcher:
    """Exact normalised match first (rule), then rapidfuzz WRatio over the whole vocabulary."""
    def __init__(self, vocab: Vocab, pool: int = 25):
        self.V, self.pool = vocab, pool
        self.exact: dict[str, list[int]] = collections.defaultdict(list)
        for i, t in enumerate(vocab.texts):
            self.exact[t].append(i)

    def match(self, text: str, hospital: str) -> tuple[str | None, float, str]:
        hits = [i for i in self.exact.get(text, []) if self.V.allowed(i, hospital)]
        if hits:
            votes = collections.Counter()
            for i in hits:
                votes[self.V.codes[i]] += 1 + self.V.n_hosp[i]
            return votes.most_common(1)[0][0], 1.0, "exact"
        for text_i, score, i in process.extract(text, self.V.texts, scorer=fuzz.WRatio, limit=self.pool, processor=None):
            if self.V.allowed(i, hospital):
                return self.V.codes[i], score / 100.0, "fuzzy"
        return None, 0.0, "none"


class EmbeddingMatcher:
    def __init__(self, vocab: Vocab, cache: Path = OUT / "vocab_embeddings.npy"):
        from sentence_transformers import SentenceTransformer
        self.V = vocab
        self.model = SentenceTransformer(MODEL, device="mps")
        if cache.exists():
            emb = np.load(cache)
        else:
            t = time.monotonic()
            emb = self.model.encode(vocab.texts, batch_size=256, normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True)
            np.save(cache, emb)
            self.build_seconds = round(time.monotonic() - t, 1)
        self.index = faiss.IndexFlatIP(emb.shape[1]); self.index.add(emb.astype("float32"))

    def encode(self, texts):
        return self.model.encode(texts, batch_size=128, normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True).astype("float32")

    def match_vec(self, vec, hospital: str, k: int = 60, top: int = 10):
        sims, ids = self.index.search(vec[None, :], k)
        best: dict[str, float] = {}
        for s, i in zip(sims[0], ids[0]):
            if i >= 0 and self.V.allowed(int(i), hospital):
                c = self.V.codes[int(i)]
                best[c] = max(best.get(c, -1.0), float(s))
        ranked = sorted(best.items(), key=lambda kv: -kv[1])[:top]
        return ranked            # [(code, sim), ...]

    def match(self, text: str, hospital: str):
        r = self.match_vec(self.encode([text])[0], hospital)
        return (r[0][0], r[0][1]) if r else (None, 0.0)
