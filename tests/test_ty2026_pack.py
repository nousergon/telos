"""TY2026 (provisional) parameter-pack verification.

Same transcription cross-check as ``test_ty2025_pack.py``: each Rev. Proc.
rate-table row prints the cumulative tax at the bracket's lower boundary
("$11,600 plus 22% of the excess over $100,800"); ``tax_from_brackets``
evaluated exactly at every boundary must reproduce those printed constants,
validating boundaries and rates simultaneously.

The pack is PROVISIONAL: values are primary-sourced (Rev. Proc. 2025-32 +
OBBBA-amended IRC), but the final 2026 form instructions are unpublished —
telos-ops#13 flips it to final against the final forms.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from telos.engine import marginal_rate, tax_from_brackets
from telos.params import load_pack

D = Decimal
PACK_PATH = Path(__file__).parent.parent / "params" / "ty2026.yaml"


@pytest.fixture(scope="module")
def pack():
    return load_pack(PACK_PATH)


class TestPackLoads:
    def test_loads_as_provisional(self, pack):
        """Stays provisional until telos-ops#13 verifies against the final
        2026 forms/instructions (~Nov 2026 - Jan 2027)."""
        assert pack.tax_year == 2026
        assert pack.status == "provisional"

    def test_every_status_has_brackets_and_deduction(self, pack):
        for fs in (
            "single",
            "married_filing_jointly",
            "married_filing_separately",
            "head_of_household",
            "qualifying_surviving_spouse",
        ):
            assert len(pack.brackets(f"ordinary_brackets.{fs}")) == 7
            assert pack.get(f"standard_deduction.{fs}").value > 0


# Printed cumulative constants from Rev. Proc. 2025-32 §4.01, quoted verbatim
# from the tables. Keyed by (filing_status, boundary) -> printed constant.
REV_PROC_CONSTANTS = {
    # Table 3 — Unmarried Individuals: "$1,240 plus 12% ... over $12,400";
    # "$5,800 plus 22% ... over $50,400"; "$17,966 plus 24% ... over
    # $105,700"; "$41,024 plus 32% ... over $201,775"; "$58,448 plus 35% ...
    # over $256,225"; "$192,979.25 plus 37% ... over $640,600".
    "single": [
        (12_400, "1240"),
        (50_400, "5800"),
        (105_700, "17966"),
        (201_775, "41024"),
        (256_225, "58448"),
        (640_600, "192979.25"),
    ],
    # Table 1 — MFJ/QSS: "$2,480 plus 12% ... over $24,800"; "$11,600 plus
    # 22% ... over $100,800"; "$35,932 plus 24% ... over $211,400"; "$82,048
    # plus 32% ... over $403,550"; "$116,896 plus 35% ... over $512,450";
    # "$206,583.50 plus 37% ... over $768,700".
    "married_filing_jointly": [
        (24_800, "2480"),
        (100_800, "11600"),
        (211_400, "35932"),
        (403_550, "82048"),
        (512_450, "116896"),
        (768_700, "206583.50"),
    ],
    # Table 2 — HOH: "$1,770 plus 12% ... over $17,700"; "$7,740 plus 22% ...
    # over $67,450"; "$16,155 plus 24% ... over $105,700"; "$39,207 plus 32%
    # ... over $201,750"; "$56,631 plus 35% ... over $256,200"; "$191,171
    # plus 37% ... over $640,600".
    "head_of_household": [
        (17_700, "1770"),
        (67_450, "7740"),
        (105_700, "16155"),
        (201_750, "39207"),
        (256_200, "56631"),
        (640_600, "191171"),
    ],
    # Table 4 — MFS: same rows as single through $256,225, then
    # "$103,291.75 plus 37% ... over $384,350".
    "married_filing_separately": [
        (12_400, "1240"),
        (50_400, "5800"),
        (105_700, "17966"),
        (201_775, "41024"),
        (256_225, "58448"),
        (384_350, "103291.75"),
    ],
}
REV_PROC_CONSTANTS["qualifying_surviving_spouse"] = REV_PROC_CONSTANTS[
    "married_filing_jointly"
]


class TestBracketTranscription:
    @pytest.mark.parametrize("filing_status", sorted(REV_PROC_CONSTANTS))
    def test_boundary_constants_match_printed_rev_proc_values(self, pack, filing_status):
        schedule = pack.brackets(f"ordinary_brackets.{filing_status}")
        for boundary, printed in REV_PROC_CONSTANTS[filing_status]:
            computed = tax_from_brackets(D(boundary), schedule)
            assert computed == D(printed), (
                f"{filing_status} @ {boundary}: engine says {computed}, "
                f"Rev. Proc. 2025-32 prints {printed}"
            )

    def test_top_marginal_rate_is_37pct_everywhere(self, pack):
        for fs in REV_PROC_CONSTANTS:
            assert marginal_rate(D(10_000_000), pack.brackets(f"ordinary_brackets.{fs}")) == D(
                "0.37"
            )


class TestSpotChecksAgainstCitedDocuments:
    def test_standard_deduction(self, pack):
        """Rev. Proc. 2025-32 §4.14(1): $16,100 single/MFS, $32,200 MFJ/QSS,
        $24,150 HOH."""
        assert pack.get("standard_deduction.single").value == D(16_100)
        assert pack.get("standard_deduction.married_filing_jointly").value == D(32_200)
        assert pack.get("standard_deduction.head_of_household").value == D(24_150)

    def test_ltcg_breakpoints_single(self, pack):
        """Rev. Proc. 2025-32 §4.03: 'All Other Individuals' Maximum Zero Rate
        Amount $49,450; Maximum 15% Rate Amount $545,500."""
        assert pack.get("ltcg.zero_rate_max.single").value == D(49_450)
        assert pack.get("ltcg.fifteen_rate_max.single").value == D(545_500)

    def test_salt_cap_and_phase_down_statutory_2026(self, pack):
        """IRC §164(b)(6) as amended by OBBBA §70120: $40,400 cap / $505,000
        threshold for taxable years beginning in 2026; 30% phase-down;
        $10,000 floor."""
        assert pack.get("salt.cap").value == D(40_400)
        assert pack.get("salt.magi_phase_down_threshold").value == D(505_000)
        assert pack.get("salt.floor").value == D(10_000)
        assert pack.get("salt.phase_down_rate").value == D("0.30")

    def test_qbi_threshold(self, pack):
        """Rev. Proc. 2025-32 §4.26: 'All Other Returns' threshold $201,750,
        phase-in range amount $276,750 (MFS is $201,775/$276,775 — the one
        status where MFS differs from single)."""
        assert pack.get("qbi.threshold.single").value == D(201_750)
        assert pack.get("qbi.phase_in_range_top.single").value == D(276_750)
        assert pack.get("qbi.threshold.married_filing_separately").value == D(201_775)

    def test_niit_statutory(self, pack):
        assert pack.get("niit.rate").value == D("0.038")
        assert pack.get("niit.magi_threshold.single").value == D(200_000)

    def test_additional_medicare_statutory(self, pack):
        assert pack.get("additional_medicare.rate").value == D("0.009")
        assert pack.get("additional_medicare.threshold.single").value == D(200_000)

    def test_amt_exemption_and_obbba_phaseout(self, pack):
        """Rev. Proc. 2025-32 §4.10: exemption $90,100 (unmarried), threshold
        $500,000; the 50% phaseout rate (OBBBA §70107) must reproduce the
        printed complete-phaseout amounts: $680,200 = $500,000 + $90,100/0.50
        (unmarried) and $1,280,400 = $1,000,000 + $140,200/0.50 (joint)."""
        exemption = pack.get("amt.exemption.single").value
        threshold = pack.get("amt.exemption_phaseout_threshold.single").value
        rate = pack.get("amt.exemption_phaseout_rate").value
        assert exemption == D(90_100)
        assert threshold == D(500_000)
        assert rate == D("0.50")
        assert threshold + exemption / rate == D(680_200)
        mfj_exemption = pack.get("amt.exemption.married_filing_jointly").value
        mfj_threshold = pack.get(
            "amt.exemption_phaseout_threshold.married_filing_jointly"
        ).value
        assert mfj_threshold + mfj_exemption / rate == D(1_280_400)

    def test_every_source_cites_a_named_document(self, pack):
        """No bare or placeholder citations anywhere in the pack."""

        def walk(node):
            if isinstance(node, dict):
                if "value" in node:
                    yield node["source"]
                else:
                    for child in node.values():
                        yield from walk(child)
            elif isinstance(node, list):
                for row in node:
                    yield row["source"]

        for src in walk(pack.values):
            assert "Rev. Proc. 2025-32" in src or "IRC §" in src, (
                f"citation not anchored to a primary document: {src!r}"
            )
