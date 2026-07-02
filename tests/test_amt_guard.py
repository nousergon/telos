"""AMT trigger guard — hard triggers, screen arithmetic, conservatism."""

from decimal import Decimal
from pathlib import Path

import pytest

from telos.engine.amt_guard import AmtGuardInputs, AmtReviewRequired, amt_screen
from telos.models import FilingStatus
from telos.params import load_pack

D = Decimal
PACK = load_pack(Path(__file__).parent.parent / "params" / "ty2025.yaml")


def inputs(**overrides):
    base = dict(
        filing_status=FilingStatus.SINGLE,
        taxable_income=D(150_000),
        deduction_addback=D(15_750),  # standard deduction
        regular_tax=D(29_000),
    )
    base.update(overrides)
    return AmtGuardInputs(**base)


class TestHardTriggers:
    @pytest.mark.parametrize(
        ("field", "value", "needle"),
        [
            ("iso_exercise_spread", D(50_000), "ISO"),
            ("private_activity_bond_interest", D(1_000), "private-activity"),
            ("other_amt_adjustments", D(-2_000), "other AMT adjustments"),
            ("has_depreciation_or_passive_adjustments", True, "depreciation"),
            ("has_general_business_credit", True, "general business credit"),
            ("has_prior_year_amt_credit", True, "8801"),
        ],
    )
    def test_each_trigger_raises(self, field, value, needle):
        with pytest.raises(AmtReviewRequired, match=needle):
            amt_screen(inputs(**{field: value}), PACK)

    def test_mfs_refused(self):
        with pytest.raises(AmtReviewRequired, match="MFS"):
            amt_screen(inputs(filing_status=FilingStatus.MARRIED_FILING_SEPARATELY), PACK)


class TestScreenArithmetic:
    def test_typical_w2_return_passes(self):
        """Taxable 150,000 std deduction: AMTI 165,750; exemption 88,100
        (no phaseout); base 77,650; TMT = 26% * 77,650 = 20,189 << 29,000."""
        r = amt_screen(inputs(), PACK)
        assert r.amti == D(165_750)
        assert r.exemption == D(88_100)
        assert r.tentative_minimum_tax == D("20189.00")

    def test_salt_heavy_return_fires(self):
        """Taxable 200,000 itemized with 60,000 of Schedule A line 7 taxes:
        AMTI 260,000; base 171,900; TMT = 26% * 171,900 = 44,694 > 98% of
        regular tax 41,063 (TCW at 200,000) -> review required."""
        with pytest.raises(AmtReviewRequired, match="screen fired"):
            amt_screen(
                inputs(
                    taxable_income=D(200_000),
                    deduction_addback=D(60_000),
                    regular_tax=D(41_063),
                ),
                PACK,
            )

    def test_preferential_income_lowers_screen_tmt(self):
        """Same profile as the firing case but 100,000 of the base is
        preferential: TMT = 26% * 71,900 + 15% * 100,000 = 33,694 — but the
        REGULAR tax on that return is also lower; with regular 41,063 the
        screen passes, showing Part III handling prevents false fires."""
        r = amt_screen(
            inputs(
                taxable_income=D(200_000),
                deduction_addback=D(60_000),
                preferential_income=D(100_000),
                regular_tax=D(41_063),
            ),
            PACK,
        )
        assert r.tentative_minimum_tax == D("33694.00")

    def test_exemption_phases_out_at_25pct(self):
        """AMTI 726,350 (taxable 700,000 + addback 26,350): excess over
        626,350 is 100,000 -> phaseout 25,000 -> exemption 63,100."""
        r = amt_screen(
            inputs(
                taxable_income=D(700_000),
                deduction_addback=D(26_350),
                regular_tax=D(216_120),
            ),
            PACK,
        )
        assert r.exemption == D(63_100)

    def test_exemption_zero_at_complete_phaseout(self):
        """The printed worksheet note: exemption is zero at AMTI >= 978,750
        single (= 626,350 + 4 * 88,100). Very high ordinary income also has
        regular tax far above TMT, so the screen passes with exemption 0."""
        r = amt_screen(
            inputs(
                taxable_income=D(1_000_000),
                deduction_addback=D(15_750),
                regular_tax=D(332_848),
            ),
            PACK,
        )
        assert r.exemption == D(0)

    def test_28pct_rate_above_breakpoint(self):
        """Ordinary base 300,000: TMT = 26% * 239,100 + 28% * 60,900
        = 62,166 + 17,052 = 79,218."""
        r = amt_screen(
            inputs(
                taxable_income=D(372_350),
                deduction_addback=D(15_750),
                regular_tax=D(99_870),
            ),
            PACK,
        )
        assert r.tentative_minimum_tax == D("79218.00")

    def test_explanation_cites_instructions(self):
        r = amt_screen(inputs(), PACK)
        assert any("6251" in s for s in r.explanation.all_sources())
        assert any("Rev. Proc. 2024-40" in s for s in r.explanation.all_sources())
