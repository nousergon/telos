"""TY2026 (provisional) Ohio parameter-pack verification (telos-ops#21).

The ``nonbusiness_brackets``, ``business_income_deduction.flat_rate_on_remainder``,
and ``estimated_tax`` sections are CONFIRMED against the real, currently
published 2026 Ohio Estimated Income Tax Payment Worksheet (IT 1040 ES) —
fetched 2026-07-03 from dam.assets.ohio.gov. The ``exemption`` tiers and the
BID cap are carried forward from the TY2025 IT 1040 booklet and stay
provisional until the real TY2026 IT 1040 instruction booklet is published
(the ITES worksheet's own exemption shortcut is a DIFFERENT, simplified
mechanism — not the filing-computation table this engine implements).
"""

from decimal import Decimal
from pathlib import Path

import pytest

from telos.engine.ohio import (
    OhioNonresidentInputs,
    _nonbusiness_tax,
    ohio_estimated_tax_check,
    ohio_nonresident,
)
from telos.models import FilingStatus
from telos.params import load_pack

D = Decimal
PACK_PATH = Path(__file__).parent.parent / "params" / "ty2026_oh.yaml"


@pytest.fixture(scope="module")
def pack():
    return load_pack(PACK_PATH)


class TestPackLoads:
    def test_loads_as_provisional(self, pack):
        """Stays provisional until the real TY2026 IT 1040 booklet is
        published and the exemption/BID sections are confirmed against it."""
        assert pack.tax_year == 2026
        assert pack.status == "provisional"


class TestBracketsUnchangedFromTy2025:
    """The 2026 ITES worksheet prints the SAME nonbusiness bracket table as
    TY2025 — confirmed directly against the primary source, not assumed."""

    def test_zero_bracket(self, pack):
        assert _nonbusiness_tax(D(26_050), pack) == D(0)

    def test_mid_bracket_matches_2025_printed_example(self, pack):
        """The booklet's TY2025 worked example (taxable nonbusiness income
        $68,050 -> $342 + 2.75% * 42,000 = $1,497) still holds for TY2026
        since the worksheet reprints the identical bracket constants."""
        assert _nonbusiness_tax(D(68_050), pack) == D(1_497)

    def test_top_bracket_uses_printed_constant(self, pack):
        assert _nonbusiness_tax(D(226_100), pack) == D("6334.945")


def oh_inputs(**overrides):
    base = dict(
        filing_status=FilingStatus.SINGLE,
        federal_agi=D(338_000),
        total_business_income=D(10_000),
        ohio_sourced_business_income=D(4_000),
    )
    base.update(overrides)
    return OhioNonresidentInputs(**base)


class TestOhioNonresidentTy2026:
    def test_duplex_shaped_return_matches_2025_shape(self, pack):
        """Same inputs as the TY2025 anchor case in test_state_modules.py —
        BID/exemption/bracket values are carried forward, so the result is
        identical until the real TY2026 booklet lands."""
        r = ohio_nonresident(oh_inputs(), pack)
        assert r.lines["8a"].value == D(9_460)
        assert r.lines["nrc"].value == D(9_345)
        assert r.net_tax.value == D(115)
        assert r.filing_required is True


class TestOhioEstimatedTaxCheckTy2026:
    """Confirmed against the real 2026 ITES worksheet: 90% current-year vs
    100% prior-year (lesser of), $500 de minimis threshold."""

    def test_current_year_harbor_binds_when_no_prior_return(self, pack):
        check = ohio_estimated_tax_check(
            current_year_oh_tax=D(2_000),
            prior_year_oh_tax=None,
            oh_withholding=D(0),
            pack=pack,
        )
        assert check.required_annual_payment.value == D(1_800)  # 90% of 2,000
        assert check.balance_after_withholding.value == D(1_800)
        assert check.advisable is True

    def test_lesser_of_prior_and_current_harbor_binds(self, pack):
        """Prior-year OH tax $1,000 (100% = 1,000) is lower than 90% of a
        $2,000 current-year projection (1,800) — the lesser wins."""
        check = ohio_estimated_tax_check(
            current_year_oh_tax=D(2_000),
            prior_year_oh_tax=D(1_000),
            oh_withholding=D(0),
            pack=pack,
        )
        assert check.required_annual_payment.value == D(1_000)
        assert check.advisable is True

    def test_below_de_minimis_threshold_not_advisable_with_computation_shown(self, pack):
        check = ohio_estimated_tax_check(
            current_year_oh_tax=D(400),
            prior_year_oh_tax=None,
            oh_withholding=D(0),
            pack=pack,
        )
        # 90% of 400 = 360, below the $500 de minimis threshold.
        assert check.advisable is False
        assert "500" in check.explanation.sources[0]

    def test_withholding_reduces_balance(self, pack):
        check = ohio_estimated_tax_check(
            current_year_oh_tax=D(2_000),
            prior_year_oh_tax=None,
            oh_withholding=D(1_900),
            pack=pack,
        )
        assert check.balance_after_withholding.value == D(0)  # 1,800 - 1,900 floored at 0
        assert check.advisable is False

    def test_provenance_cites_the_2026_worksheet(self, pack):
        check = ohio_estimated_tax_check(
            current_year_oh_tax=D(2_000),
            prior_year_oh_tax=D(1_000),
            oh_withholding=D(0),
            pack=pack,
        )
        assert any("2026 Ohio Estimated Income Tax" in s for s in check.explanation.all_sources())
