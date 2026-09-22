"""Download CMS reference data (HCPCS Level II, MS-DRG Table 5) with hash + manifest.

CPT descriptions are AMA-copyrighted and are NOT in these files; see DECISIONS.md ADR-004.
"""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[3]
REF = ROOT / "data" / "reference"
UA = "PriceCheck-research/0.1 (public price-transparency research project)"
SOURCES = {
    "hcpcs_2026-10": "https://www.cms.gov/files/zip/october-2026-alpha-numeric-hcpcs-file.zip",
    "msdrg_fy2026_table5": "https://www.cms.gov/files/zip/fy2026-ipps-fr-table-5.zip",
}

def main() -> None:
    REF.mkdir(parents=True, exist_ok=True)
    for key, url in SOURCES.items():
        t0 = time.monotonic()
        r = requests.get(url, headers={"User-Agent": UA}, timeout=120)
        r.raise_for_status()
        sha = hashlib.sha256(r.content).hexdigest()
        dest = REF / f"{key}.zip"
        dest.write_bytes(r.content)
        rec = {"key": key, "url": url, "sha256": sha, "size_bytes": len(r.content),
               "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "last_modified": r.headers.get("last-modified"), "duration_s": round(time.monotonic() - t0, 2)}
        with (REF / "manifest.jsonl").open("a") as f:
            f.write(json.dumps(rec) + "\n")
        print(rec)
        time.sleep(2)

if __name__ == "__main__":
    main()
