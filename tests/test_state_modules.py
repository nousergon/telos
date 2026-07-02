"""Ohio nonresident + WA excise checker — printed-example and hand-computed cases."""

from decimal import Decimal
from pathlib import Path

from telos.engine.ohio import OhioNonresidentInputs, _nonbusiness_tax, ohio_nonresident
from telos.engine.wa_excise import wa_excise_check
from telos.models import FilingStatus
from telos.params import load_pack

D = Decimal
ROOT = Path(__file__).parent.parent
OH = load_pack(ROOT / "params" / "ty2025_oh.yaml")
WA = load_pack(ROOT / "params" / "ty2025_wa.yaml")


class TestOhioBracketTable:
    def test_booklet_printed_example(self):
        """The booklet's own worked example (p.18): taxable nonbusiness
        income $68,050 -> $342 + 2.75% * 42,000 = $1,497."""
        assert _nonbusiness_tax(D(68_050), OH) == D(1_497)

    def test_zero_bracket(self):
        assert _nonbusiness_tax(D(26_050), OH) == D(0)

    def test_the_342_discontinuity_is_real(self):
        """Ohio's printed table jumps $342 at the zero-bracket edge — we
        implement the printed law, not a smoothed version."""
        assert _nonbusiness_tax(D("26050.01"), OH) > D(342)

    def test_top_bracket_uses_printed_constant(self):
        """$226,100 taxable: 2,394.32 + 3.125% * 126,100 = 2,394.32 +
        3,940.625 = 6,334.945 (unrounded)."""
        assert _nonbusiness_tax(D(226_100), OH) == D("6334.945")


def oh_inputs(**overrides):
    base = dict(
        filing_status=FilingStatus.SINGLE,
        federal_agi=D(338_000),
        total_business_income=D(10_000),
        ohio_sourced_business_income=D(4_000),
    )
    base.update(overrides)
    return OhioNonresidentInputs(**base)


class TestOhioNonresident:
    def test_duplex_shaped_return_small_net_tax(self):
        """Fed AGI 338,000; total business income 10,000, Ohio share 4,000.
        BID 10,000; OAGI 328,000; MAGI 338,000 -> exemption 1,900; line 5 =
        326,100; line 6 = 0; line 7 = 326,100; 8a = round(2,394.32 +
        3.125% * 226,100) = 9,460; 8b = 0. IT NRC (filed mechanics): Ohio
        portion = 4,000 UN-netted; ratio = trunc4(324,000/328,000 =
        0.987804...) = 0.9878; NRC = round(9,460 * 0.9878) = 9,345 ->
        net 115. Filing required."""
        r = ohio_nonresident(oh_inputs(), OH)
        assert r.lines["3"].value == D(328_000)
        assert r.lines["4"].value == D(1_900)
        assert r.lines["8a"].value == D(9_460)
        assert r.lines["8b"].value == D(0)
        assert r.lines["nrc"].value == D(9_345)
        assert r.net_tax.value == D(115)
        assert r.filing_required is True

    def test_bid_exhausted_ohio_tax_due(self):
        """All-Ohio business income 300,000 over the 250,000 BID: fed AGI
        320,000 -> OAGI 70,000; MAGI 320,000 -> exemption 1,900; line 5 =
        68,100; line 6 = 50,000 @ 3% = 1,500 (8b); line 7 = 18,100 -> 8a =
        0. Ohio portion = 300,000 UN-netted, exceeds OAGI -> ratio clamps
        to 0 -> NRC 0 -> net = 1,500 (all-Ohio income gets no credit)."""
        r = ohio_nonresident(
            oh_inputs(
                federal_agi=D(320_000),
                total_business_income=D(300_000),
                ohio_sourced_business_income=D(300_000),
            ),
            OH,
        )
        assert r.lines["6"].value == D(50_000)
        assert r.lines["8a"].value == D(0)
        assert r.lines["8b"].value == D(1_500)
        assert r.lines["nrc"].value == D(0)
        assert r.net_tax.value == D(1_500)

    def test_ohio_rental_loss_no_tax_filing_still_flagged(self):
        r = ohio_nonresident(
            oh_inputs(total_business_income=D(-3_000),
                      ohio_sourced_business_income=D(-3_000)),
            OH,
        )
        assert r.net_tax.value == D(0)
        assert r.filing_required is True  # a loss year still files the NRC shape

    def test_exemption_tiers_from_pack(self):
        low = ohio_nonresident(oh_inputs(federal_agi=D(35_000),
                                         total_business_income=D(0),
                                         ohio_sourced_business_income=D(0)), OH)
        assert low.lines["4"].value == D(2_400)
        ultra = ohio_nonresident(oh_inputs(federal_agi=D(800_000)), OH)
        assert ultra.lines["4"].value == D(0)

    def test_mfs_bid_cap(self):
        r = ohio_nonresident(
            oh_inputs(filing_status=FilingStatus.MARRIED_FILING_SEPARATELY,
                      total_business_income=D(200_000),
                      ohio_sourced_business_income=D(200_000)),
            OH,
        )
        # BID capped at 125,000 -> taxable business income 75,000
        assert r.lines["6"].value == D(75_000)

    def test_provenance_cites_the_booklet(self):
        r = ohio_nonresident(oh_inputs(), OH)
        assert any("Ohio IT 1040 instructions" in s for s in r.net_tax.all_sources())


class TestWaExciseChecker:
    def test_below_deduction_not_applicable_with_computation_shown(self):
        d = wa_excise_check(D(60_000), WA)
        assert d.applicable is False
        assert d.tax == D(0)
        assert "278000" in d.explanation.sources[0]

    def test_above_deduction_seven_percent(self):
        """1,200,000 gain: taxable 922,000 -> 7% = 64,540."""
        d = wa_excise_check(D(1_200_000), WA)
        assert d.applicable is True
        assert d.taxable_gain == D(922_000)
        assert d.tax == D(64_540)

    def test_surcharge_tier_above_1m_taxable(self):
        """1,500,000 gain: taxable 1,222,000. Per the dor.wa.gov tiered-rates
        notice, 7% applies to ALL taxable gains and the 2.9% surcharge stacks
        on the excess over $1M (9.9% marginal): 7% * 1,222,000 + 2.9% *
        222,000 = 85,540 + 6,438 = 91,978. (This test caught a first-draft
        bug that capped the 7% at $1M.)"""
        d = wa_excise_check(D(1_500_000), WA)
        assert d.tax == D(91_978)

    def test_at_exactly_the_deduction(self):
        assert wa_excise_check(D(278_000), WA).applicable is False
