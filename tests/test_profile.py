import json
import zipfile

from pricecheck.ingest import profile

TALL = (
    "hospital_name,last_updated_on,version,location_name\n"
    "Test Hosp,2026-01-01,3.0.0,Main\n"
    "description,code|1,code|1|type,standard_charge|gross,standard_charge|negotiated_dollar,payer_name,plan_name\n"
    "Aspirin,123,CPT,10.5,,,\n"
    "Aspirin,123,CPT,,9.0,Acme,Gold\n"
)
WIDE = (
    "hospital_name,last_updated_on,version\nTest Hosp,2026-01-01,2.0.0\n"
    "description,code|1,standard_charge|gross,standard_charge|Acme|Gold|negotiated_dollar,standard_charge|Beta|Silver|negotiated_dollar\n"
    "Aspirin,123,10.5,9.0,8.0\n"
)
JSON_DOC = {"hospital_name": "Test Hosp", "version": "3.0.0", "last_updated_on": "2026-01-01",
            "standard_charge_information": [{"description": "a", "code_information": []}, {"description": "b"}]}


def run(tmp_path, name, content, root_patch):
    p = tmp_path / name
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content)
    return profile.profile_file(p)


def test_tall_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "ROOT", tmp_path)
    r = run(tmp_path, "t.csv", TALL, None)
    assert r["layout"] == "csv_tall" and r["data_rows"] == 2 and r["declared_version"] == "3.0.0"


def test_wide_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "ROOT", tmp_path)
    r = run(tmp_path, "w.csv", WIDE, None)
    assert r["layout"] == "csv_wide" and r["wide_payer_columns"] == 2


def test_json(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "ROOT", tmp_path)
    r = run(tmp_path, "j.json", json.dumps(JSON_DOC), None)
    assert r["layout"] == "json" and r["standard_charge_items"] == 2 and r["declared_version"] == "3.0.0"


def test_zipped_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "ROOT", tmp_path)
    z = tmp_path / "z.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("inner.csv", TALL)
    r = profile.profile_file(z)
    assert r["container"]["kind"] == "zip" and r["layout"] == "csv_tall"


def test_ragged_rows_are_counted_not_hidden(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "ROOT", tmp_path)
    r = run(tmp_path, "r.csv", TALL + "only,two\n", None)
    assert r["ragged_rows"] == 1


def test_json_with_utf8_bom(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "ROOT", tmp_path)
    r = run(tmp_path, "bom.json", b"\xef\xbb\xbf" + json.dumps(JSON_DOC).encode(), None)
    assert r["layout"] == "json" and r["standard_charge_items"] == 2
