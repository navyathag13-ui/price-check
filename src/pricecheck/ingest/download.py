"""Polite, resumable bronze downloader.

Rules it enforces: one request at a time per host, a fixed delay between
requests, an identifying User-Agent, robots.txt recorded (not bypassed),
raw bytes stored untouched under a content-hash path, and every fetch
(success or failure) appended to an append-only manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
import yaml

ROOT = Path(__file__).resolve().parents[3]
BRONZE = ROOT / "data" / "bronze"
MANIFEST = BRONZE / "manifest.jsonl"
USER_AGENT = "PriceCheck-research/0.1 (public price-transparency research project)"
HOST_DELAY_S = 2.0
CHUNK = 1024 * 1024
RETRIES = 3


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def filename_from(resp: requests.Response, url: str) -> str:
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)"?', cd)
    name = unquote(m.group(1)) if m else Path(unquote(urlparse(url).path)).name
    name = re.sub(r"[^A-Za-z0-9._ ()-]", "_", name).strip() or "download.bin"
    return name


def append_manifest(rec: dict) -> None:
    BRONZE.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def manifest_records() -> list[dict]:
    if not MANIFEST.exists():
        return []
    return [json.loads(l) for l in MANIFEST.read_text().splitlines() if l.strip()]


def fetch_robots(session: requests.Session, url: str) -> dict:
    p = urlparse(url)
    robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
    try:
        r = session.get(robots_url, timeout=20)
        return {"robots_url": robots_url, "status": r.status_code,
                "body_head": r.text[:600] if r.status_code == 200 else None}
    except requests.RequestException as e:
        return {"robots_url": robots_url, "status": None, "error": str(e)}


def download_one(session: requests.Session, h: dict) -> dict:
    url = h["mrf_url"]
    if not urlparse(url).scheme:
        url = "https://" + url
    rec = {"slug": h["slug"], "requested_url": url, "fetched_at": utcnow(),
           "user_agent": USER_AGENT, "robots": fetch_robots(session, url)}
    time.sleep(HOST_DELAY_S)
    incoming = BRONZE / "_incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    part = incoming / f"{h['slug']}.part"
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            t0 = time.monotonic()
            sha = hashlib.sha256()
            size = 0
            with session.get(url, stream=True, timeout=(20, 120), allow_redirects=True) as r:
                rec.update(status=r.status_code, final_url=r.url,
                           headers={k.lower(): v for k, v in r.headers.items()
                                    if k.lower() in ("content-type", "content-length", "last-modified", "etag",
                                                     "content-disposition", "server")})
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                with part.open("wb") as f:
                    for chunk in r.iter_content(CHUNK):
                        f.write(chunk)
                        sha.update(chunk)
                        size += len(chunk)
                name = filename_from(r, r.url)
            dur = time.monotonic() - t0
            digest = sha.hexdigest()
            dest_dir = BRONZE / h["slug"] / digest
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / name
            if dest.exists():
                part.unlink()
                rec["outcome"] = "unchanged_duplicate"
            else:
                shutil.move(str(part), dest)
                os.chmod(dest, 0o444)
                rec["outcome"] = "stored"
            rec.update(sha256=digest, size_bytes=size, filename=name, attempts=attempt,
                       duration_s=round(dur, 2), mb_per_s=round(size / 1e6 / dur, 2) if dur else None,
                       path=str(dest.relative_to(ROOT)))
            return rec
        except Exception as e:  # noqa: BLE001 - recorded, not swallowed
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(5 * attempt)
    rec.update(outcome="failed", error=last_err, attempts=RETRIES)
    if part.exists():
        part.unlink()
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", action="append", help="only these slugs")
    ap.add_argument("--skip-existing", action="store_true", help="skip slugs already stored")
    ns = ap.parse_args()
    hospitals = yaml.safe_load((ROOT / "config" / "hospitals.yaml").read_text())["hospitals"]
    done = {r["slug"] for r in manifest_records() if r.get("outcome") in ("stored", "unchanged_duplicate")}
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    last_host = None
    for h in hospitals:
        if ns.slug and h["slug"] not in ns.slug:
            continue
        if ns.skip_existing and h["slug"] in done:
            print(f"skip {h['slug']}")
            continue
        host = urlparse(h["mrf_url"] if "//" in h["mrf_url"] else "https://" + h["mrf_url"]).netloc
        if host == last_host:
            time.sleep(HOST_DELAY_S)
        last_host = host
        rec = download_one(session, h)
        append_manifest(rec)
        if rec.get("outcome") == "stored":   # real new content, not a re-fetch of something already seen
            from pricecheck.streaming.produce import emit, make_event
            ev = make_event(h["slug"], rec["sha256"], rec["size_bytes"], rec["outcome"])
            result = emit(ev)
            print(f"  -> file-changed event emitted ({result['backend']}): {result['detail']}", flush=True)
        print(f"{h['slug']:28s} {rec['outcome']:20s} {rec.get('size_bytes', 0)/1e6:9.1f} MB "
              f"{rec.get('duration_s', '-')}s {rec.get('error', '')}", flush=True)


if __name__ == "__main__":
    main()
