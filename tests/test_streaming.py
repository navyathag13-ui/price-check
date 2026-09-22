"""produce.py (both backends) and consume.reprocess's three real outcomes, on tiny synthetic fixtures."""
import json

from pricecheck.streaming import produce as P


def test_make_event_has_required_fields():
    ev = P.make_event("h", "sha", 100, "stored")
    assert ev.slug == "h" and ev.sha256 == "sha" and ev.event_id


def test_emit_falls_back_to_local_file_when_eventhub_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "LOCAL_EVENTS_DIR", tmp_path)
    for k in ("EVENTHUB_NAMESPACE", "EVENTHUB_NAME", "EVENTHUB_CONNECTION_STRING"):
        monkeypatch.delenv(k, raising=False)
    ev = P.make_event("h", "sha", 100, "stored")
    result = P.emit(ev)
    assert result["backend"] == "local_file"
    written = json.loads(Path(result["detail"]).read_text()) if (Path := __import__("pathlib").Path) else None
    assert written["slug"] == "h" and written["sha256"] == "sha"


def test_eventhub_backend_requires_all_three_vars(monkeypatch):
    monkeypatch.setenv("EVENTHUB_NAMESPACE", "x"); monkeypatch.setenv("EVENTHUB_NAME", "x")
    monkeypatch.delenv("EVENTHUB_CONNECTION_STRING", raising=False)
    assert P._eventhub_configured() is False
    monkeypatch.setenv("EVENTHUB_CONNECTION_STRING", "x")
    assert P._eventhub_configured() is True


def make_hospital(tmp_path, monkeypatch, csv_text, sha="abc"):
    """Same fixture shape as test_quarantine_e2e.py, reused here for consume.reprocess."""
    from pricecheck.silver import contract as C
    from pricecheck.silver import pipeline as PL

    (tmp_path / f"data/bronze/h/{sha}").mkdir(parents=True)
    f = tmp_path / f"data/bronze/h/{sha}/h.csv"
    f.write_text(csv_text)
    monkeypatch.setattr(PL, "ROOT", tmp_path)
    from pricecheck import streaming
    monkeypatch.setattr(streaming.consume, "ROOT", tmp_path)
    cdir = tmp_path / "contracts"; cdir.mkdir(exist_ok=True)
    monkeypatch.setattr(C, "CONTRACT_DIR", cdir)
    import yaml
    (cdir / "h.v1.yaml").write_text(yaml.safe_dump({"source": "h", "layout": "csv_tall", "accepted_template_versions": ["3.0.0"],
                                                     "required_columns": ["description"], "max_reject_rate": 0.5}))
    prof = {"slug": "h", "sha256": sha, "file": f"data/bronze/h/{sha}/h.csv", "layout": "csv_tall", "declared_version": "3.0.0"}
    (tmp_path / "data/bronze/profile.jsonl").write_text(json.dumps(prof) + "\n")
    (tmp_path / "data/bronze/manifest.jsonl").write_text(json.dumps({"slug": "h", "sha256": sha,
                                                                     "path": f"data/bronze/h/{sha}/h.csv", "outcome": "stored"}) + "\n")


GOOD = "h,v\nH,3.0.0\ndescription,code|1,standard_charge|gross\nAsp,123,10.50\n"
BAD = "h,v\nH,3.0.0\ndescription\nAsp\n"   # missing code|1 -> quarantined


def test_reprocess_stale_event_is_skipped(tmp_path, monkeypatch):
    from pricecheck.streaming.consume import reprocess
    make_hospital(tmp_path, monkeypatch, GOOD)
    r = reprocess("h", "not-the-real-sha")
    assert r["status"] == "skipped" and "stale" in r["reason"]


def test_reprocess_quarantines_a_bad_file(tmp_path, monkeypatch):
    from pricecheck.streaming.consume import reprocess
    make_hospital(tmp_path, monkeypatch, BAD)
    r = reprocess("h", "abc")
    assert r["status"] == "quarantined" and r["detail"]


def test_reprocess_promotes_and_loads_history_then_is_idempotent(tmp_path, monkeypatch):
    from pricecheck.streaming.consume import reprocess
    make_hospital(tmp_path, monkeypatch, GOOD)
    r1 = reprocess("h", "abc")
    assert r1["status"] == "reprocessed" and r1["history_mode"] == "initial"
    r2 = reprocess("h", "abc")
    assert r2["status"] == "already_current"
