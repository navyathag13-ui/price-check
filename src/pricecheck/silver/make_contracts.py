"""Derive v1 contracts from what each real file actually contains, recording deviations from CMS-required columns."""
import csv
import io
import json

import yaml

from pricecheck.ingest.profile import ROOT, open_payload
from pricecheck.silver import contract as C

DEPRECATED = {"2.0.0"}

def header(path):
    with open_payload(path) as (stream, inner, _):
        text = io.TextIOWrapper(stream, encoding="utf-8-sig", errors="cp1252_fallback", newline="")
        r = csv.reader(text); next(r); next(r); return next(r)

def main():
    prof = {}
    for l in open(ROOT / "data/bronze/profile.jsonl"):
        p = json.loads(l); prof[p["slug"]] = p
    C.CONTRACT_DIR.mkdir(exist_ok=True)
    for slug, p in sorted(prof.items()):
        layout, ver = p["layout"], p.get("declared_version")
        path = ROOT / p["file"]
        if layout == "json":
            req, fixed, dev = list(C.JSON_TOP_REQUIRED), [], []
        else:
            cols = header(path)
            cand = C.TALL_CANDIDATES if layout == "csv_tall" else C.WIDE_CANDIDATES
            req = [c for c in cand if c in cols]
            dev = [f"file lacks CMS-required column {c!r}" for c in cand if c not in cols]
            fixed = [c for c in cols if layout == "csv_tall" or C.split_wide_header(c) is None]
        con = C.Contract(source=slug, layout=layout, accepted_template_versions=sorted({ver, "3.0.0"} if ver in DEPRECATED else {ver}),
                         deprecated_template_versions=[ver] if ver in DEPRECATED else [], required_columns=req,
                         expected_fixed_columns=fixed, known_deviations=dev)
        (C.CONTRACT_DIR / f"{slug}.v1.yaml").write_text(yaml.safe_dump(json.loads(con.model_dump_json()), sort_keys=False, width=200))
        print(f"{slug:28s} {layout:9s} v{ver} required={len(req)} deviations={dev}")

if __name__ == "__main__":
    main()
