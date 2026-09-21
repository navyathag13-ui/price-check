"""End-to-end: contract violation -> quarantine record + alert, and NOTHING promoted to silver."""
import json

import yaml

from pricecheck.silver import contract as C
from pricecheck.silver import pipeline as P

GOOD_COLS = ("description,code|1,code|1|type,setting,billing_class,standard_charge|gross,standard_charge|discounted_cash,"
             "payer_name,plan_name,standard_charge|negotiated_dollar,standard_charge|min,standard_charge|max")


def setup(tmp_path, monkeypatch, csv_text, required):
    (tmp_path / "data/bronze/t/abc").mkdir(parents=True)
    f = tmp_path / "data/bronze/t/abc/t.csv"
    f.write_text(csv_text)
    monkeypatch.setattr(P, "ROOT", tmp_path)
    cdir = tmp_path / "contracts"; cdir.mkdir()
    monkeypatch.setattr(C, "CONTRACT_DIR", cdir)
    (cdir / "t.v1.yaml").write_text(yaml.safe_dump({"source": "t", "layout": "csv_tall", "accepted_template_versions": ["3.0.0"],
                                                     "required_columns": required, "max_reject_rate": 0.5}))
    prof = {"slug": "t", "sha256": "abc", "file": "data/bronze/t/abc/t.csv", "layout": "csv_tall", "declared_version": "3.0.0"}
    (tmp_path / "data/bronze/profile.jsonl").write_text(json.dumps(prof) + "\n")
    return {"path": "data/bronze/t/abc/t.csv", "sha256": "abc"}


def test_missing_required_column_is_quarantined_with_alert(tmp_path, monkeypatch):
    csv_text = "h,v\nH,3.0.0\ndescription,code|1\nAsp,123\n"
    rec = setup(tmp_path, monkeypatch, csv_text, ["description", "code|1", "standard_charge|gross"])
    res = P.run_one("t", rec, None, tmp_path)
    assert res["outcome"] == "quarantined"
    q = json.loads((tmp_path / "quarantine/t/abc.json").read_text())
    assert any("missing required columns" in v for v in q["violations"])
    alerts = [json.loads(l) for l in (tmp_path / "alerts.jsonl").read_text().splitlines()]
    assert alerts[0]["severity"] == "error" and alerts[0]["type"] == "contract_violation"
    assert not (tmp_path / "silver/canonical").exists()


def test_high_reject_rate_is_quarantined_and_output_removed(tmp_path, monkeypatch):
    rows = "".join(f"Asp,,CPT,both,facility,{p},,A,PPO,,,\n" for p in ("N/A", "-1", "x", "y")) + "Ok,1,CPT,both,facility,10,,,,,,\n"
    rec = setup(tmp_path, monkeypatch, f"h,v\nH,3.0.0\n{GOOD_COLS}\n{rows}", ["description"])
    res = P.run_one("t", rec, None, tmp_path)
    assert res["outcome"] == "quarantined"
    assert not list((tmp_path / "silver/canonical").glob("**/*.parquet")) if (tmp_path / "silver/canonical").exists() else True


def test_clean_file_is_promoted_and_idempotent(tmp_path, monkeypatch):
    rows = "Asp,123,CPT,both,facility,10,8,A,PPO,7,1,20\n"
    rec = setup(tmp_path, monkeypatch, f"h,v\nH,3.0.0\n{GOOD_COLS}\n{rows}", ["description"])
    first = P.run_one("t", rec, None, tmp_path)
    assert first["outcome"] == "promoted" and first["rows_out"] == 5
    assert P.run_one("t", rec, None, tmp_path)["outcome"] == "skipped_already_done"
