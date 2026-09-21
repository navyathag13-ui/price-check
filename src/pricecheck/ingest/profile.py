"""Streaming layout profiler for hospital MRFs (CSV tall / CSV wide / JSON, optionally zipped).

Reports only what it observes: layout, declared version, columns, row/item counts.
It does not fix or interpret anything; parsing and contracts come in Phase 2.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path

import ijson

ROOT = Path(__file__).resolve().parents[3]
BRONZE = ROOT / "data" / "bronze"
WIDE_RE = re.compile(r"^(standard_charge|estimated_amount)\|[^|]+\|[^|]+\|", re.I)


@contextmanager
def open_payload(path: Path):
    """Yield (binary_stream, inner_name, container). Zip -> first csv/json member."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            members = [i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith((".csv", ".json"))]
            if not members:
                raise ValueError(f"zip has no csv/json member: {[i.filename for i in z.infolist()]}")
            m = members[0]
            with z.open(m) as f:
                yield f, m.filename, {"kind": "zip", "members": [i.filename for i in z.infolist()],
                                      "inner_size_bytes": m.file_size}
    else:
        with path.open("rb") as f:
            yield f, path.name, {"kind": "plain"}


def sniff_json(first: bytes) -> bool:
    return first.lstrip(b"\xef\xbb\xbf \r\n\t")[:1] in (b"{", b"[")


def profile_csv(stream) -> dict:
    text = io.TextIOWrapper(stream, encoding="utf-8-sig", errors="replace", newline="")
    reader = csv.reader(text)
    try:
        meta_keys = next(reader)
        meta_vals = next(reader)
        cols = next(reader)
    except StopIteration:
        return {"layout": "unparseable", "error": "fewer than 3 header rows"}
    meta = dict(zip([k.strip() for k in meta_keys], meta_vals))
    wide = sum(1 for c in cols if WIDE_RE.match(c.strip()))
    layout = "csv_wide" if wide else "csv_tall"
    n = 0
    ragged = 0
    width = len(cols)
    for row in reader:
        n += 1
        if len(row) != width:
            ragged += 1
    return {"layout": layout, "declared_version": next((v for k, v in meta.items() if k.lower() == "version"), None),
            "meta_keys": [k for k in meta if k], "n_columns": width, "wide_payer_columns": wide,
            "columns_head": cols[:12], "data_rows": n, "ragged_rows": ragged,
            "hospital_name_declared": next((v for k, v in meta.items() if k.lower().startswith("hospital_name")), None),
            "last_updated_on": next((v for k, v in meta.items() if k.lower().startswith("last_updated")), None)}


def profile_json(stream) -> dict:
    top: dict = {}
    items = 0
    depth_key = None
    for prefix, event, value in ijson.parse(stream):
        if prefix.count(".") == 0 and event in ("string", "number", "boolean", "null") and prefix:
            top[prefix] = value
        elif prefix.count(".") == 0 and event == "start_array" and prefix:
            top.setdefault("_arrays", []).append(prefix)
        if prefix == "standard_charge_information.item" and event == "start_map":
            items += 1
    return {"layout": "json", "declared_version": top.get("version"), "top_level_scalars":
            {k: (v if not isinstance(v, (int, float)) else float(v)) for k, v in top.items() if k != "_arrays"},
            "top_level_arrays": top.get("_arrays", []), "standard_charge_items": items,
            "hospital_name_declared": top.get("hospital_name"), "last_updated_on": top.get("last_updated_on")}


def profile_file(path: Path) -> dict:
    t0 = time.monotonic()
    with open_payload(path) as (stream, inner, container):
        buffered = io.BufferedReader(stream, 1 << 20) if not hasattr(stream, "peek") else stream
        head = buffered.peek(16)[:16]
        if head.startswith(b"\xef\xbb\xbf"):  # UTF-8 BOM: valid text, but yajl rejects it
            buffered.read(3)
            head = buffered.peek(16)[:16]
        body = profile_json(buffered) if sniff_json(head) else profile_csv(buffered)
    return {"file": str(path.relative_to(ROOT)), "inner_name": inner, "container": container, **body,
            "profile_seconds": round(time.monotonic() - t0, 1)}


def main() -> None:
    manifest = [json.loads(l) for l in (BRONZE / "manifest.jsonl").read_text().splitlines() if l.strip()]
    latest = {r["slug"]: r for r in manifest if r.get("outcome") in ("stored", "unchanged_duplicate")}
    only = set(sys.argv[1:])
    out = BRONZE / "profile.jsonl"
    for slug, rec in latest.items():
        if only and slug not in only:
            continue
        try:
            p = profile_file(ROOT / rec["path"])
        except Exception as e:  # noqa: BLE001 - recorded
            p = {"file": rec["path"], "layout": "error", "error": f"{type(e).__name__}: {e}"}
        p["slug"] = slug
        p["sha256"] = rec["sha256"]
        with out.open("a") as f:
            f.write(json.dumps(p, sort_keys=True, default=str) + "\n")
        print(slug, p.get("layout"), p.get("data_rows") or p.get("standard_charge_items"), p.get("declared_version"), flush=True)


if __name__ == "__main__":
    main()
