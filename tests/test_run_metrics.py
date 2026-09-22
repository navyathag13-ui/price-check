"""run_metrics consolidation, built from tiny synthetic per-stage logs (not the real multi-GB logs)."""
import json

from pricecheck.observability import run_metrics as RM


def test_from_bronze_maps_real_manifest_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(RM, "ROOT", tmp_path)
    (tmp_path / "data/bronze").mkdir(parents=True)
    rec = {"slug": "h", "outcome": "stored", "fetched_at": "2026-01-01T00:00:00+00:00", "duration_s": 1.5}
    (tmp_path / "data/bronze/manifest.jsonl").write_text(json.dumps(rec) + "\n")
    rows = RM.from_bronze()
    assert len(rows) == 1 and rows[0]["stage"] == "bronze_download" and rows[0]["outcome"] == "stored"


def test_from_silver_maps_real_run_log_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(RM, "ROOT", tmp_path)
    (tmp_path / "data/silver").mkdir(parents=True)
    rec = {"slug": "h", "sha256": "abc123", "at": "t", "source_rows_in": 10, "rows_out": 9, "rejects": 1,
           "duration_s": 0.5, "outcome": "promoted", "reject_reasons": {"row:no_code": 1}}
    (tmp_path / "data/silver/run_log.jsonl").write_text(json.dumps(rec) + "\n")
    rows = RM.from_silver()
    assert rows[0]["rows_in"] == 10 and rows[0]["rows_rejected"] == 1


def test_build_returns_zero_rows_note_when_nothing_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(RM, "ROOT", tmp_path)
    monkeypatch.setattr(RM, "TABLE", tmp_path / "data/delta/run_metrics")
    assert RM.build() == {"rows": 0, "note": "no per-stage logs found yet"}
