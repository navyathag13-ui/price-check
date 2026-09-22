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


def _real_file_for(slug: str) -> dict | None:
    """The committed manifest/profile.jsonl are small index files kept as evidence of a real run; the multi-GB raw
    bronze files they point at are gitignored and won't exist in a fresh clone or CI. Skip per-hospital, not on the
    index file's existence, or CI runs the body and fails on a missing multi-GB file instead of skipping cleanly."""
    if not (ROOT / "data/bronze/profile.jsonl").exists():
        return None
    prof = [json.loads(l) for l in (ROOT / "data/bronze/profile.jsonl").read_text().splitlines() if slug in l]
    p = next((p for p in prof if p["slug"] == slug), None)
    return p if p and (ROOT / p["file"]).exists() else None


@pytest.mark.parametrize("slug", SLUGS)
def test_contract_accepts_current_real_file(slug):
    p = _real_file_for(slug)
    if p is None:
        pytest.skip(f"raw bronze file for '{slug}' not present locally (gitignored; not in a fresh clone or CI)")
    from pricecheck.silver.pipeline import observed_header
    layout, ver, cols = observed_header(ROOT / p["file"], p)
    errs, _ = C.validate_header(C.load(slug), layout, ver, cols)
    assert errs == []
