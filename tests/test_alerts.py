"""Alerting logic on tiny synthetic manifest/profile histories (not the real multi-GB logs)."""
import json
from datetime import datetime, timezone

from pricecheck.observability import alerts as A


def write_jsonl(path, recs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in recs))


def test_shrink_detected_when_new_file_under_half_previous_size(tmp_path):
    p = tmp_path / "manifest.jsonl"
    write_jsonl(p, [{"slug": "h", "outcome": "stored", "size_bytes": 1_000_000, "fetched_at": "2026-01-01"},
                    {"slug": "h", "outcome": "stored", "size_bytes": 300_000, "fetched_at": "2026-02-01"}])
    out = A.check_shrink_and_disappearance(p)
    assert any(a.kind == "shrink" for a in out)


def test_no_shrink_alert_for_a_modest_decrease(tmp_path):
    p = tmp_path / "manifest.jsonl"
    write_jsonl(p, [{"slug": "h", "outcome": "stored", "size_bytes": 1_000_000, "fetched_at": "2026-01-01"},
                    {"slug": "h", "outcome": "stored", "size_bytes": 800_000, "fetched_at": "2026-02-01"}])
    assert A.check_shrink_and_disappearance(p) == []


def test_three_consecutive_failures_alert(tmp_path):
    p = tmp_path / "manifest.jsonl"
    write_jsonl(p, [{"slug": "h", "outcome": "stored", "size_bytes": 100, "fetched_at": "2026-01-01"}] +
                   [{"slug": "h", "outcome": "failed", "fetched_at": f"2026-02-0{i}"} for i in range(1, 4)])
    out = A.check_shrink_and_disappearance(p)
    assert any(a.kind == "repeated_failure" for a in out)


def test_two_failures_then_a_success_does_not_alert(tmp_path):
    p = tmp_path / "manifest.jsonl"
    write_jsonl(p, [{"slug": "h", "outcome": "failed", "fetched_at": "2026-01-01"},
                    {"slug": "h", "outcome": "failed", "fetched_at": "2026-01-02"},
                    {"slug": "h", "outcome": "stored", "size_bytes": 100, "fetched_at": "2026-01-03"}])
    out = A.check_shrink_and_disappearance(p)
    assert not any(a.kind == "repeated_failure" for a in out)


def test_layout_change_is_error_version_change_is_warning(tmp_path):
    p = tmp_path / "profile.jsonl"
    write_jsonl(p, [{"slug": "h", "layout": "csv_tall", "declared_version": "2.0.0"},
                    {"slug": "h", "layout": "json", "declared_version": "3.0.0"}])
    out = A.check_shape_change(p)
    kinds = {(a.kind, a.severity) for a in out}
    assert ("layout_change", "error") in kinds and ("version_change", "warning") in kinds


def test_freshness_flags_stale_and_unparseable(tmp_path):
    p = tmp_path / "profile.jsonl"
    write_jsonl(p, [{"slug": "fresh", "last_updated_on": "2026-09-01"}, {"slug": "old", "last_updated_on": "2020-01-01"},
                    {"slug": "bad", "last_updated_on": "not-a-date"}])
    out = A.check_freshness(p, as_of=datetime(2026, 9, 22, tzinfo=timezone.utc))
    kinds = {a.slug: a.kind for a in out}
    assert kinds.get("old") == "stale" and kinds.get("bad") == "unparseable_date" and "fresh" not in kinds
