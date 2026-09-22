"""Freshness + shape-change alerting: a file that changed shape, disappeared, or shrank sharply.

Compares the CURRENT bronze manifest entry for each hospital against its PREVIOUS one (by fetch time). Pure function
over already-collected evidence (bronze manifest, silver profile) -- no new scraping, no cloud dependency.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SHRINK_THRESHOLD = 0.5     # alert if a new file is less than half the size of the previous one
STALE_DAYS = 45            # CMS requires at least annual updates; this is a much tighter operational trigger


@dataclass
class Alert:
    severity: str   # "error" | "warning"
    slug: str
    kind: str
    message: str


def _history_by_slug(manifest_path: Path) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    if not manifest_path.exists():
        return by
    for l in manifest_path.read_text().splitlines():
        r = json.loads(l)
        by.setdefault(r["slug"], []).append(r)
    for slug in by:
        by[slug].sort(key=lambda r: r.get("fetched_at", ""))
    return by


def check_shrink_and_disappearance(manifest_path: Path = ROOT / "data/bronze/manifest.jsonl") -> list[Alert]:
    alerts: list[Alert] = []
    for slug, recs in _history_by_slug(manifest_path).items():
        ok = [r for r in recs if r.get("outcome") in ("stored", "unchanged_duplicate")]
        if len(ok) >= 2:
            prev, cur = ok[-2], ok[-1]
            prev_size, cur_size = prev.get("size_bytes", 0), cur.get("size_bytes", 0)
            if prev_size and cur_size and cur_size < prev_size * SHRINK_THRESHOLD:
                alerts.append(Alert("error", slug, "shrink",
                                    f"{slug}: file shrank from {prev_size/1e6:.1f}MB to {cur_size/1e6:.1f}MB "
                                    f"({100*cur_size/prev_size:.0f}% of previous)"))
        last_fail_streak = 0
        for r in reversed(recs):
            if r.get("outcome") == "failed":
                last_fail_streak += 1
            else:
                break
        if last_fail_streak >= 3:
            alerts.append(Alert("error", slug, "repeated_failure", f"{slug}: last {last_fail_streak} fetch attempts all failed"))
    return alerts


def check_shape_change(profile_path: Path = ROOT / "data/bronze/profile.jsonl") -> list[Alert]:
    alerts: list[Alert] = []
    if not profile_path.exists():
        return alerts
    by: dict[str, list[dict]] = {}
    for l in profile_path.read_text().splitlines():
        r = json.loads(l)
        by.setdefault(r["slug"], []).append(r)
    for slug, recs in by.items():
        if len(recs) < 2:
            continue
        prev, cur = recs[-2], recs[-1]
        if prev.get("layout") != cur.get("layout"):
            alerts.append(Alert("error", slug, "layout_change", f"{slug}: layout changed {prev.get('layout')} -> {cur.get('layout')}"))
        if prev.get("declared_version") != cur.get("declared_version"):
            alerts.append(Alert("warning", slug, "version_change",
                                f"{slug}: template version changed {prev.get('declared_version')} -> {cur.get('declared_version')}"))
    return alerts


def check_freshness(profile_path: Path = ROOT / "data/bronze/profile.jsonl", as_of: datetime | None = None) -> list[Alert]:
    from pricecheck.quality.scores import parse_date
    as_of = as_of or datetime.now(timezone.utc)
    alerts: list[Alert] = []
    if not profile_path.exists():
        return alerts
    latest: dict[str, dict] = {}
    for l in profile_path.read_text().splitlines():
        r = json.loads(l)
        latest[r["slug"]] = r      # last write wins; profile.jsonl is append-only in fetch order
    for slug, r in latest.items():
        d = parse_date(r.get("last_updated_on"))
        if d is None:
            alerts.append(Alert("warning", slug, "unparseable_date", f"{slug}: last_updated_on={r.get('last_updated_on')!r} not parseable"))
            continue
        days = (as_of.date() - d).days
        if days > STALE_DAYS:
            alerts.append(Alert("warning", slug, "stale", f"{slug}: last updated {days} days ago (threshold {STALE_DAYS})"))
    return alerts


def run_all() -> list[Alert]:
    return check_shrink_and_disappearance() + check_shape_change() + check_freshness()


if __name__ == "__main__":
    for a in run_all():
        print(f"[{a.severity.upper()}] {a.kind}: {a.message}")
