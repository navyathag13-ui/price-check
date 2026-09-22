import re
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pricecheck.matching.normalize import code_family, normalize

ROOT = Path(__file__).resolve().parents[1]


@given(st.one_of(st.none(), st.text()))
def test_normalize_never_raises_and_output_is_clean(s):
    out = normalize(s)
    assert re.fullmatch(r"[a-z0-9' ]*", out) is not None and out == out.strip() and "  " not in out


@given(st.text())
def test_normalize_is_idempotent(s):
    once = normalize(s)
    assert normalize(once) == once


def test_normalize_known_hospital_habits():
    assert normalize("HC MRI BRAIN W/O CONTRAST") == "magnetic resonance imaging brain without contrast"
    assert normalize("PR INJ TRIAMCINOLONE 40MG/ML") == "injection triamcinolone 40 mg ml"
    assert normalize("HCHG 64795 BIOPSY OF NERVE") == "64795 biopsy of nerve"
    assert normalize("EXC LESION W/ REPAIR") == "exc lesion with repair"


def test_code_family():
    assert code_family("73723") == "cpt_numeric" and code_family("470") == "ms_drg" and code_family("J1885") == "drug_J"
    assert code_family("C1713") == "device_or_other_hcpcs" and code_family("") == "other"


def test_leave_one_hospital_out_mask_logic():
    import numpy as np

    from pricecheck.matching.matchers import Vocab
    v = Vocab.__new__(Vocab)
    v.bits = {"h1": 1, "h2": 2}
    v.masks = np.array([1, 3, 1 << 40], dtype=np.int64)   # h1 only; h1+h2; CMS
    assert not v.allowed(0, "h1")            # own-only entry excluded
    assert v.allowed(1, "h1") and v.allowed(1, "h2") and v.allowed(0, "h2")
    assert v.allowed(2, "h1")                # CMS reference always usable


@pytest.mark.skipif(not (ROOT / "data/reference/hcpcs_2026-10.zip").exists(), reason="reference data not present")
def test_hcpcs_reference_parses_real_file():
    from pricecheck.matching.vocab import hcpcs_reference, msdrg_reference
    h = hcpcs_reference(); m = msdrg_reference()
    assert len(h) == 8770 and h.code.str.fullmatch(r"[A-Z][0-9]{4}").all()
    assert "ketorolac" in h[h.code == "J1885"].raw.iloc[0].lower()
    assert len(m) > 700 and "HEART TRANSPLANT" in m[m.code == "001"].raw.iloc[0]
