"""Contract tests: every committed contract loads, and matches the real profiled bronze headers when present."""
import json
from pathlib import Path

import pytest
import yaml

from pricecheck.silver import contract as C

ROOT = Path(__file__).resolve().parents[1]
SLUGS = [p.name.split(".")[0] for p in sorted((ROOT / "contracts").glob("*.v1.yaml"))]
HOSPITALS = {h["slug"] for h in yaml.safe_load((ROOT / "config/hospitals.yaml").read_text())["hospitals"]}


def test_every_contract_source_is_a_registered_hospital():
    assert SLUGS and set(SLUGS) <= HOSPITALS


@pytest.mark.parametrize("slug", SLUGS)
def test_contract_loads_and_is_internally_consistent(slug):
    c = C.load(slug)
    assert c.source == slug and c.accepted_template_versions and c.required_columns
    assert set(c.deprecated_template_versions) <= set(c.accepted_template_versions)
    assert 0 < c.max_reject_rate < 1


@pytest.mark.skipif(not (ROOT / "data/bronze/profile.jsonl").exists(), reason="bronze not present (CI has no raw data)")
@pytest.mark.parametrize("slug", SLUGS)
def test_contract_accepts_current_real_file(slug):
    from pricecheck.silver.pipeline import observed_header
    prof = [json.loads(l) for l in (ROOT / "data/bronze/profile.jsonl").read_text().splitlines() if slug in l]
    p = next(p for p in prof if p["slug"] == slug)
    layout, ver, cols = observed_header(ROOT / p["file"], p)
    errs, _ = C.validate_header(C.load(slug), layout, ver, cols)
    assert errs == []
