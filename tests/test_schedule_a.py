"""Schedule A — SALT phase-down cases + deduction choice, TY2025 pack."""

from decimal import Decimal
from pathlib import Path

import pytest

from telos.engine import Form1040Inputs, assemble_1040
from telos.engine.guard import CoverageError
from telos.engine.schedule_a import ScheduleAInputs, choose_deduction, schedule_a
from telos.models import W2, FilingStatus
from telos.params import load_pack

D = Decimal
PACK = load_pack(Path(__file__).parent.parent / "params" / "ty2025.yaml")


def inputs(**overrides):
    base = dict(
        filing_status=FilingStatus.SINGLE,
        agi=D(300_000),
        real_estate_taxes=D(14_000),
        state_local_income_or_sales_tax=D(3_000),
        mortgage_interest_1098=D(18_000),
        charitable_cash=D(2_500),
    )
    base.update(overrides)
    return ScheduleAInputs(**base)


class TestSaltPhaseDown:
    def test_under_cap_no_limitation(self):
        """5d = 17,000 < 40,000 cap; MAGI 300,000 < 500,000 -> 5e = 5d."""
        r = schedule_a(inputs(), PACK)
        assert r.lines["5d"].value == D(17_000)
        assert r.lines["5e"].value == D(17_000)

    def test_cap_binds_without_phase_down(self):
        """5d = 45,000, MAGI 300,000 -> 5e = 40,000 (cap, no phase-down)."""
        r = schedule_a(inputs(real_estate_taxes=D(42_000)), PACK)
        assert r.lines["5e"].value == D(40_000)

    def test_phase_down_partial(self):
        """MAGI 550,000: reduction = 30% * 50,000 = 15,000 -> cap 25,000.
        5d = 45,000 -> 5e = 25,000."""
        r = schedule_a(inputs(agi=D(550_000), real_estate_taxes=D(42_000)), PACK)
        assert r.lines["5e"].value == D(25_000)

    def test_phase_down_hits_floor_exactly(self):
        """MAGI 600,000: reduction = 30,000 -> cap 10,000 == floor."""
        r = schedule_a(inputs(agi=D(600_000), real_estate_taxes=D(42_000)), PACK)
        assert r.lines["5e"].value == D(10_000)

    def test_floor_binds_beyond(self):
        """MAGI 700,000: reduction 60,000 would give -20,000 -> floor 10,000."""
        r = schedule_a(inputs(agi=D(700_000), real_estate_taxes=D(42_000)), PACK)
        assert r.lines["5e"].value == D(10_000)

    def test_mfs_uses_mfs_parameters(self):
        """MFS: cap 20,000, threshold 250,000, floor 5,000. MAGI 300,000:
        reduction 15,000 -> cap 5,000 == floor."""
        r = schedule_a(
            inputs(filing_status=FilingStatus.MARRIED_FILING_SEPARATELY,
                   agi=D(300_000), real_estate_taxes=D(25_000)),
            PACK,
        )
        assert r.lines["5e"].value == D(5_000)

    def test_phase_down_citation_in_provenance(self):
        r = schedule_a(inputs(agi=D(550_000), real_estate_taxes=D(42_000)), PACK)
        assert any("phase-down" in s for s in r.lines["5e"].all_sources())


class TestOtherSections:
    def test_medical_floor(self):
        """Medical 25,000, AGI 300,000: floor 22,500 -> line 4 = 2,500."""
        r = schedule_a(inputs(medical_expenses=D(25_000)), PACK)
        assert r.lines["4"].value == D(2_500)

    def test_medical_below_floor_zero(self):
        r = schedule_a(inputs(medical_expenses=D(10_000)), PACK)
        assert r.lines["4"].value == D(0)

    def test_total_line17_hand_computed(self):
        """Default inputs: taxes 17,000 + interest 18,000 + charity 2,500
        = 37,500."""
        r = schedule_a(inputs(), PACK)
        assert r.total_itemized.value == D(37_500)

    def test_cash_gift_agi_guard_fires(self):
        with pytest.raises(CoverageError, match="60% of AGI"):
            schedule_a(inputs(charitable_cash=D(200_000)), PACK)

    def test_noncash_gift_agi_guard_fires(self):
        with pytest.raises(CoverageError, match="30% of AGI"):
            schedule_a(inputs(charitable_noncash=D(100_000)), PACK)


class TestChooseDeduction:
    def test_itemized_wins(self):
        r = schedule_a(inputs(), PACK)  # 37,500 vs standard 15,750
        choice = choose_deduction(r, FilingStatus.SINGLE, PACK)
        assert choice.value == D(37_500)
        assert "itemized 37500 >= standard 15750" in choice.sources[0]

    def test_standard_wins(self):
        r = schedule_a(
            inputs(real_estate_taxes=D(3_000), state_local_income_or_sales_tax=D(0),
                   mortgage_interest_1098=D(4_000), charitable_cash=D(500)),
            PACK,
        )
        choice = choose_deduction(r, FilingStatus.SINGLE, PACK)
        assert choice.value == D(15_750)
        assert "standard 15750 > itemized 7500" in choice.sources[0]

    def test_both_totals_in_provenance_either_way(self):
        r = schedule_a(inputs(), PACK)
        choice = choose_deduction(r, FilingStatus.SINGLE, PACK)
        srcs = " | ".join(choice.all_sources())
        assert "OBBBA" in srcs  # standard-deduction citation present as the loser too

    def test_feeds_assembly_itemized_seam(self):
        r = schedule_a(inputs(), PACK)
        choice = choose_deduction(r, FilingStatus.SINGLE, PACK)
        result = assemble_1040(
            Form1040Inputs(
                filing_status=FilingStatus.SINGLE,
                w2s=(W2(employer="Acme", wages=D(300_000)),),
                itemized_deduction=choice.value,
            ),
            PACK,
        )
        assert result.lines["12"].value == D(37_500)
