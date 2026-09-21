"""Incremental load driver: bronze manifest -> (silver if needed) -> history Delta, skipping unchanged content hashes."""
from __future__ import annotations

import argparse
from pathlib import Path

from pricecheck.history import delta_store as D
from pricecheck.silver import pipeline as P

ROOT = Path(__file__).resolve().parents[3]
HISTORY = ROOT / "data/delta/price_history"
LEDGER = ROOT / "data/delta/ingestion_ledger"
TMP = ROOT / "data/tmp"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", action="append")
    ns = ap.parse_args()
    loaded = {(r["slug"], r["source_sha256"]) for r in D.ledger_records(LEDGER)}
    for slug, rec in P.latest_bronze().items():
        if ns.slug and slug not in ns.slug:
            continue
        sha = rec["sha256"]
        if (slug, sha) in loaded:
            print(f"{slug:28s} unchanged (sha {sha[:10]} already loaded) -> skipped")
            continue
        glob = f"{ROOT}/data/silver/canonical/hospital={slug}/source_sha256={sha}/part-*.parquet"
        if not (ROOT / f"data/silver/canonical/hospital={slug}/source_sha256={sha}/_SUCCESS").exists():
            s = P.run_one(slug, rec, None, ROOT / "data")
            if s["outcome"] != "promoted":
                print(f"{slug:28s} silver {s['outcome']} -> not loaded to history")
                continue
        r = D.load_version(HISTORY, LEDGER, slug, sha, glob, TMP)
        print(f"{slug:28s} {r['mode']:8s} staged={r.get('staged_rows'):>11,} +{r.get('rows_inserted'):,} -{r.get('rows_closed'):,} "
              f"={r.get('rows_unchanged'):,} v{r.get('history_version_after')} {r.get('duration_s')}s", flush=True)


if __name__ == "__main__":
    main()
