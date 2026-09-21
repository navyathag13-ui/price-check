"""Bronze -> silver: validate against the contract, quarantine on violation, else write canonical + rejects."""
from __future__ import annotations

import argparse
import itertools
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from pricecheck.ingest.profile import open_payload, profile_file
from pricecheck.silver import contract as C
from pricecheck.silver.model import CANONICAL_SCHEMA, REJECT_SCHEMA, Decoder, Reject
from pricecheck.silver.parsers import PARSERS, Ctx

ROOT = Path(__file__).resolve().parents[3]
BATCH = 250_000


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def jl_append(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(rec, sort_keys=True, default=str) + "\n")


def latest_bronze() -> dict[str, dict]:
    man = [json.loads(l) for l in (ROOT / "data/bronze/manifest.jsonl").read_text().splitlines() if l.strip()]
    return {r["slug"]: r for r in man if r.get("outcome") in ("stored", "unchanged_duplicate")}


def observed_header(path: Path, prof: dict) -> tuple[str, str | None, list[str]]:
    layout, ver = prof["layout"], prof.get("declared_version")
    if layout == "json":
        return layout, ver, list(prof.get("top_level_scalars", {})) + prof.get("top_level_arrays", [])
    import csv, io
    with open_payload(path) as (stream, _, _):
        r = csv.reader(io.TextIOWrapper(stream, encoding="utf-8-sig", errors="cp1252_fallback", newline=""))
        next(r); next(r)
        return layout, ver, next(r)


def quarantine(slug: str, sha: str, errors: list[str], warns: list[str], out_root: Path) -> dict:
    rec = {"slug": slug, "sha256": sha, "at": now(), "violations": errors, "warnings": warns}
    p = out_root / "quarantine" / slug / f"{sha}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=2))
    jl_append(out_root / "alerts.jsonl", {"severity": "error", "type": "contract_violation", **rec})
    return rec


def run_one(slug: str, rec: dict, limit: int | None, out_root: Path, force: bool = False) -> dict:
    t0 = time.monotonic()
    path = ROOT / rec["path"]
    sha = rec["sha256"]
    final = out_root / "silver" / "canonical" / f"hospital={slug}" / f"source_sha256={sha}"
    if (final / "_SUCCESS").exists() and not force:
        return {"slug": slug, "outcome": "skipped_already_done"}
    con = C.load(slug)
    prof = next((p for p in map(json.loads, (ROOT / "data/bronze/profile.jsonl").read_text().splitlines())
                 if p["slug"] == slug and p["sha256"] == sha), None) or {**profile_file(path), "slug": slug}
    layout, ver, cols = observed_header(path, prof)
    errors, warns = C.validate_header(con, layout, ver, cols)
    if warns:
        jl_append(out_root / "alerts.jsonl", {"severity": "warning", "type": "contract_warning", "slug": slug,
                                              "sha256": sha, "at": now(), "warnings": warns})
    if errors:
        quarantine(slug, sha, errors, warns, out_root)
        return {"slug": slug, "sha256": sha, "outcome": "quarantined", "violations": errors}

    tmp = final.with_name(final.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    Decoder.count = 0
    ctx = Ctx(con, sha, ver)
    reasons: dict[str, int] = {}
    rows_out = n_rej = part = 0
    buf: list[dict] = []
    rbuf: list[dict] = []
    ptypes: dict[str, int] = {}

    def flush_main():
        nonlocal buf, part
        if buf:
            pq.write_table(pa.Table.from_pylist(buf, schema=CANONICAL_SCHEMA), tmp / f"part-{part:05d}.parquet", compression="zstd")
            part += 1
            buf = []

    with open_payload(path) as (stream, inner, container):
        it = PARSERS[layout](stream, ctx)
        for out in it:
            if isinstance(out, Reject):
                n_rej += 1
                key = f"{out.kind}:{out.reason}"
                reasons[key] = reasons.get(key, 0) + 1
                rbuf.append({"hospital_slug": slug, "source_sha256": sha, "source_row": out.source_row, "kind": out.kind,
                             "reason": out.reason, "field": out.field, "raw": out.raw})
            else:
                rows_out += 1
                ptypes[out["price_type"]] = ptypes.get(out["price_type"], 0) + 1
                buf.append(out)
                if len(buf) >= BATCH:
                    flush_main()
            if limit and ctx.stats.rows_in >= limit:
                break
    flush_main()
    if rbuf:   # own subfolder so a glob over canonical parts never picks up the differently-shaped rejects
        (tmp / "rejects").mkdir()
        pq.write_table(pa.Table.from_pylist(rbuf, schema=REJECT_SCHEMA), tmp / "rejects" / "rejects.parquet", compression="zstd")
    rate = n_rej / max(rows_out + n_rej, 1)
    dur = round(time.monotonic() - t0, 1)
    stats = {"slug": slug, "sha256": sha, "at": now(), "layout": layout, "template_version": ver,
             "contract_version": con.contract_version, "source_rows_in": ctx.stats.rows_in, "rows_out": rows_out,
             "rejects": n_rej, "reject_rate": round(rate, 6), "reject_reasons": reasons, "rows_by_price_type": ptypes,
             "non_dollar_negotiated_cells": ctx.stats.non_dollar_negotiated, "extra": ctx.stats.extra,
             "encoding_fallback_bytes": Decoder.count, "duration_s": dur, "limited": bool(limit)}
    if rows_out == 0 or rate > con.max_reject_rate:
        shutil.rmtree(tmp, ignore_errors=True)
        q = quarantine(slug, sha, [f"reject rate {rate:.3f} > {con.max_reject_rate} or zero output rows ({rows_out})"], warns, out_root)
        stats.update(outcome="quarantined", violations=q["violations"])
    else:
        (tmp / "_SUCCESS").write_text(json.dumps(stats, default=str))
        shutil.rmtree(final, ignore_errors=True)
        tmp.rename(final)
        stats["outcome"] = "promoted"
    jl_append(out_root / "silver" / "run_log.jsonl", stats)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", action="append")
    ap.add_argument("--limit", type=int, help="stop after N source rows; writes under data/sample/ not data/")
    ap.add_argument("--force", action="store_true")
    ns = ap.parse_args()
    out_root = ROOT / "data" / ("sample" if ns.limit else "")
    for slug, rec in latest_bronze().items():
        if ns.slug and slug not in ns.slug:
            continue
        s = run_one(slug, rec, ns.limit, out_root, ns.force)
        print(slug, s.get("outcome"), s.get("source_rows_in"), s.get("rows_out"), s.get("rejects"), s.get("duration_s"), s.get("violations", ""), flush=True)


if __name__ == "__main__":
    main()
