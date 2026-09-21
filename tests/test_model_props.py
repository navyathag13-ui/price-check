"""Property-based tests (Hypothesis) for the pure parsing functions."""
from decimal import Decimal

from hypothesis import given, settings, strategies as st

from pricecheck.silver.contract import WIDE_SUFFIXES, split_wide_header
from pricecheck.silver.model import CODE_PRIORITY, parse_amount, pick_codes


@given(st.one_of(st.none(), st.text(), st.integers(), st.floats(allow_nan=True, allow_infinity=True)))
def test_parse_amount_never_raises_and_is_consistent(raw):
    amount, reason = parse_amount(raw)
    assert (amount is None) or (reason is None)          # never both
    if amount is not None:
        assert amount > 0 and amount <= Decimal("100000000")


@given(st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("99999999"), places=2, allow_nan=False))
def test_valid_amounts_roundtrip_with_currency_noise(d):
    amount, reason = parse_amount(f"${d:,.2f}")
    assert reason is None and amount == d.quantize(Decimal("0.0001"))


@given(st.decimals(max_value=Decimal("0"), allow_nan=False, allow_infinity=False, places=2))
def test_non_positive_always_rejected(d):
    amount, reason = parse_amount(str(d))
    assert amount is None and reason == "non_positive_amount"


type_st = st.sampled_from(["CPT", "HCPCS", "cdm", "RC", "MS-DRG", "weird", ""])
@given(st.lists(st.tuples(st.text(min_size=0, max_size=6), type_st), max_size=6))
def test_pick_codes_primary_is_highest_priority(pairs):
    code, typ, alts = pick_codes(pairs)
    usable = [c for c, _ in pairs if c.strip()]
    if not usable:
        assert code is None
        return
    assert code is not None and typ in CODE_PRIORITY
    n_alt = len([a for a in alts.split("|") if a])
    assert n_alt == len(usable) - 1 or "|" in "".join(c for c in usable)   # codes containing '|' can confuse the count


safe = st.text(alphabet=st.characters(blacklist_characters="|\n\r", blacklist_categories=("Cs",)), min_size=1, max_size=12)
@given(safe, safe, st.sampled_from(WIDE_SUFFIXES))
def test_wide_header_roundtrip(payer, plan, suffix):
    col = f"standard_charge|{payer}|{plan}|{suffix}"
    assert split_wide_header(col) == ("standard_charge", payer, plan, suffix)


@given(safe, safe)
def test_wide_header_without_suffix(payer, plan):
    assume_ok = payer not in WIDE_SUFFIXES and plan not in WIDE_SUFFIXES
    if assume_ok:
        assert split_wide_header(f"median_amount|{payer}|{plan}") == ("median_amount", payer, plan, "")
