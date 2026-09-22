"""Rules, feature matrix, review statistics and quality-score helpers."""
from datetime import date

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from pricecheck.anomaly import detect as DT
from pricecheck.anomaly.review import wilson
from pricecheck.quality.scores import parse_date


def frame(**kw):
    base = dict(price_type="negotiated", amount=100.0, robust_z=0.0, item_gross=100.0, item_cash=np.nan, item_min=50.0, item_max=150.0)
    base.update(kw)
    return pd.DataFrame([base])


def test_clean_price_flags_nothing():
    assert not DT.rules(frame()).iloc[0].any()


def test_each_rule_fires_on_its_own_condition():
    assert DT.rules(frame(robust_z=-5.2)).iloc[0].R1_robust_z
    assert DT.rules(frame(amount=115.0, item_max=np.nan, item_min=np.nan)).iloc[0].R2_neg_gt_gross
    assert DT.rules(frame(item_gross=np.nan, amount=170.0)).iloc[0].R3_out_of_range
    assert DT.rules(frame(item_gross=np.nan, amount=40.0)).iloc[0].R3_out_of_range
    assert DT.rules(frame(price_type="cash", amount=120.0, item_min=np.nan, item_max=np.nan)).iloc[0].R4_cash_gt_gross
    assert DT.rules(frame(amount=999999.99)).iloc[0].R5_placeholder


def test_rules_need_context_and_do_not_flag_missing_context():
    r = DT.rules(frame(item_gross=np.nan, item_min=np.nan, item_max=np.nan, amount=5000.0)).iloc[0]
    assert not (r.R2_neg_gt_gross or r.R3_out_of_range or r.R4_cash_gt_gross)


def test_known_false_positive_of_placeholder_rule_is_documented():
    """$99,999.94 is a real price for a pneumatic VAD driver (peer median $113k); R5 flags it. Kept as a pinned known limit."""
    assert DT.rules(frame(amount=99999.94)).iloc[0].R5_placeholder


@given(st.floats(min_value=0.01, max_value=1e6), st.floats(min_value=0.5, max_value=1.1))
@settings(max_examples=200)
def test_negotiated_at_or_below_gross_never_triggers_R2(gross, frac):
    r = DT.rules(frame(amount=gross * frac, item_gross=gross, item_min=np.nan, item_max=np.nan)).iloc[0]
    assert not r.R2_neg_gt_gross


def test_feature_matrix_shapes_and_finiteness():
    df = frame()
    assert DT.feature_matrix(df, "negotiated").shape == (1, 5) and DT.feature_matrix(df, "cash").shape == (1, 3)
    assert np.isfinite(DT.feature_matrix(frame(item_gross=np.nan, item_min=np.nan, item_max=np.nan), "negotiated")).all()


def test_wilson_interval_properties():
    lo, hi = wilson(5, 20)
    assert 0 <= lo < 0.25 < hi <= 1 and wilson(0, 20)[0] == 0 and wilson(0, 0) == (0.0, 0.0)


def test_parse_date_handles_both_hospital_formats():
    assert parse_date("2026-03-11") == date(2026, 3, 11) and parse_date("07/01/2026") == date(2026, 7, 1)
    assert parse_date("not a date") is None and parse_date(None) is None
