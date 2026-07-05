"""TY2024 Ohio parameter-pack verification (NON-personal; runs in CI).

Exercises the printed 2024 Ohio bracket table through the SAME ``ohio.py``
engine used for 2025, driven by the 2024 pack. TY2024 is a two-rate year
(2.75% / 3.50%) — distinct from 2025's 2.75% / 3.125% — with a different
mid-bracket base ($360.69 vs $342.00) and a three-tier exemption table (2025
added a $0 tier at $750,000). The engine is unchanged: all year variance is
in the pack, which is exactly the point of the params contract.
"""

from decimal import Decimal
from pathlib import Path

from telos.engine.ohio import OhioNonresidentInputs, _nonbusiness_tax, ohio_nonresident
from telos.models import FilingStatus
from telos.params import load_pack

D = Decimal
OH = load_pack(Path(__file__).parent.parent / "params" / "ty2024_oh.yaml")


class TestPackLoads:
    def test_loads_as_final_2024(self):
        assert OH.tax_year == 2024
        assert OH.status == "final"


class TestOhioBracketTable:
    def test_zero_bracket(self):
        assert _nonbusiness_tax(D(26_050), OH) == D(0)

    def test_the_360_discontinuity_is_real(self):
        """The 2024 printed table jumps $360.69 at the zero-bracket edge —
        we implement the printed law, not a smoothed version."""
        assert _nonbusiness_tax(D("26050.01"), OH) > D("360.69")

    def test_mid_bracket_uses_printed_base(self):
        """Taxable nonbusiness income $68,050: $360.69 + 2.75% * (68,050 -
        26,050) = 360.69 + 2.75% * 42,000 = 360.69 + 1,155.00 = 1,515.69."""
        assert _nonbusiness_tax(D(68_050), OH) == D("1515.69")

    def test_top_bracket_chains_to_printed_100k_constant(self):
        """The printed $2,394.32 top-bracket base must equal the mid-bracket
        formula evaluated at $100,000: $360.69 + 2.75% * (100,000 - 26,050) =
        360.69 + 2,033.625 = 2,394.315 -> rounds to the printed $2,394.32.
        (The pack stores the printed $2,394.32; this checks the chaining that
        produced it.)"""
        mid = _nonbusiness_tax(D(100_000), OH)
        assert mid == D("2394.315")
        assert D("2394.315").quantize(D("0.01")) == OH.get(
            "nonbusiness_brackets.top_base"
        ).value

    def test_top_bracket_uses_35pct_not_3125(self):
        """$226,100 taxable: 2,394.32 + 3.50% * 126,100 = 2,394.32 +
        4,413.50 = 6,807.82 (unrounded) — the 2024 rate is 3.50%, higher than
        2025's 3.125%."""
        assert _nonbusiness_tax(D(226_100), OH) == D("6807.82")


def oh_inputs(**overrides):
    base = dict(
        filing_status=FilingStatus.SINGLE,
        federal_agi=D(338_000),
        total_business_income=D(10_000),
        ohio_sourced_business_income=D(4_000),
    )
    base.update(overrides)
    return OhioNonresidentInputs(**base)


class TestOhioExemptionThreeTier2024:
    def test_low_magi_top_exemption(self):
        r = ohio_nonresident(
            oh_inputs(federal_agi=D(35_000), total_business_income=D(0),
                      ohio_sourced_business_income=D(0)),
            OH,
        )
        assert r.lines["4"].value == D(2_400)

    def test_mid_magi_tier2(self):
        r = ohio_nonresident(
            oh_inputs(federal_agi=D(60_000), total_business_income=D(0),
                      ohio_sourced_business_income=D(0)),
            OH,
        )
        assert r.lines["4"].value == D(2_150)

    def test_high_magi_never_phases_to_zero_in_2024(self):
        """Unlike 2025, the 2024 exemption table has NO $0 tier — even an
        ultra-high-income filer keeps the $1,900 top-tier exemption."""
        ultra = ohio_nonresident(oh_inputs(federal_agi=D(2_000_000)), OH)
        assert ultra.lines["4"].value == D(1_900)


class TestBusinessIncomeDeduction:
    def test_mfs_bid_cap(self):
        r = ohio_nonresident(
            oh_inputs(filing_status=FilingStatus.MARRIED_FILING_SEPARATELY,
                      total_business_income=D(200_000),
                      ohio_sourced_business_income=D(200_000)),
            OH,
        )
        # BID capped at 125,000 -> taxable business income 75,000
        assert r.lines["6"].value == D(75_000)

    def test_provenance_cites_the_2024_booklet(self):
        r = ohio_nonresident(oh_inputs(), OH)
        assert any("2024 Ohio IT 1040 instructions" in s for s in r.net_tax.all_sources())
