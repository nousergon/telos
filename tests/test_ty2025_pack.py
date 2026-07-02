"""TY2025 parameter-pack verification.

The transcription cross-check exploits the Rev. Proc.'s own printed
cumulative constants: each rate-table row prints the total tax at the
bracket's lower boundary ("$57,231 plus 35% of the excess over $250,525").
``tax_from_brackets`` evaluated exactly at every boundary must reproduce
those printed constants — which validates BOTH the boundaries and the rates
of the transcription simultaneously. A single transposed digit anywhere in a
schedule breaks at least one constant.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from telos.engine import marginal_rate, tax_from_brackets
from telos.params import load_pack

D = Decimal
PACK_PATH = Path(__file__).parent.parent / "params" / "ty2025.yaml"


@pytest.fixture(scope="module")
def pack():
    return load_pack(PACK_PATH)


class TestPackLoads:
    def test_loads_as_final(self, pack):
        """Flipped provisional -> final 2026-07-02 when the M1 replay gate
        passed (the filed TY2025 return reproduced to the dollar)."""
        assert pack.tax_year == 2025
        assert pack.status == "final"

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


# Printed cumulative constants from Rev. Proc. 2024-40 §2.01, quoted verbatim
# from the tables ("The Tax Is: $X plus R% of the excess over $B"). Keyed by
# (filing_status, boundary) -> printed constant at that boundary.
REV_PROC_CONSTANTS = {
    # Table 3 — Unmarried Individuals: "$1,192.50 plus 12% ... over $11,925";
    # "$5,578.50 plus 22% ... over $48,475"; "$17,651 plus 24% ... over
    # $103,350"; "$40,199 plus 32% ... over $197,300"; "$57,231 plus 35% ...
    # over $250,525"; "$188,769.75 plus 37% ... over $626,350".
    "single": [
        (11_925, "1192.50"),
        (48_475, "5578.50"),
        (103_350, "17651"),
        (197_300, "40199"),
        (250_525, "57231"),
        (626_350, "188769.75"),
    ],
    # Table 1 — MFJ/QSS: "$2,385 plus 12% ... over $23,850"; "$11,157 plus
    # 22% ... over $96,950"; "$35,302 plus 24% ... over $206,700"; "$80,398
    # plus 32% ... over $394,600"; "$114,462 plus 35% ... over $501,050";
    # "$202,154.50 plus 37% ... over $751,600".
    "married_filing_jointly": [
        (23_850, "2385"),
        (96_950, "11157"),
        (206_700, "35302"),
        (394_600, "80398"),
        (501_050, "114462"),
        (751_600, "202154.50"),
    ],
    # Table 2 — HOH: "$1,700 plus 12% ... over $17,000"; "$7,442 plus 22% ...
    # over $64,850"; "$15,912 plus 24% ... over $103,350"; "$38,460 plus 32%
    # ... over $197,300"; "$55,484 plus 35% ... over $250,500"; "$187,031.50
    # plus 37% ... over $626,350".
    "head_of_household": [
        (17_000, "1700"),
        (64_850, "7442"),
        (103_350, "15912"),
        (197_300, "38460"),
        (250_500, "55484"),
        (626_350, "187031.50"),
    ],
    # Table 4 — MFS: same rows as single through $250,525, then "$57,231 plus
    # 35% ... over $250,525" capped at $375,800: "$101,077.25 plus 37% ...
    # over $375,800".
    "married_filing_separately": [
        (11_925, "1192.50"),
        (48_475, "5578.50"),
        (103_350, "17651"),
        (197_300, "40199"),
        (250_525, "57231"),
        (375_800, "101077.25"),
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
                f"Rev. Proc. 2024-40 prints {printed}"
            )

    def test_top_marginal_rate_is_37pct_everywhere(self, pack):
        for fs in REV_PROC_CONSTANTS:
            assert marginal_rate(D(10_000_000), pack.brackets(f"ordinary_brackets.{fs}")) == D(
                "0.37"
            )


class TestSpotChecksAgainstCitedDocuments:
    def test_standard_deduction_single_obbba(self, pack):
        """IRS newsroom 'New and enhanced deductions for individuals':
        'Single or Married Filing Separately: $15,750' (OBBBA-amended §63(c),
        superseding Rev. Proc. 2024-40 §2.15's $15,000)."""
        sd = pack.get("standard_deduction.single")
        assert sd.value == D(15_750)
        assert "OBBBA" in sd.sources[0]

    def test_ltcg_breakpoints_single(self, pack):
        """Rev. Proc. 2024-40 §2.03: 'All Other Individuals' Maximum Zero Rate
        Amount $48,350; Maximum 15% Rate Amount $533,400."""
        assert pack.get("ltcg.zero_rate_max.single").value == D(48_350)
        assert pack.get("ltcg.fifteen_rate_max.single").value == D(533_400)

    def test_salt_cap_and_phase_down(self, pack):
        """2025 Instructions for Schedule A, line 5e: 'increased to $40,000
        ($20,000 if married filing separately)'; 'reduced if your modified
        adjusted gross income is more than $500,000'; 'will not be reduced
        below $10,000'."""
        assert pack.get("salt.cap").value == D(40_000)
        assert pack.get("salt.magi_phase_down_threshold").value == D(500_000)
        assert pack.get("salt.floor").value == D(10_000)
        assert pack.get("salt.phase_down_rate").value == D("0.30")

    def test_qbi_threshold_single(self, pack):
        """Rev. Proc. 2024-40 §2.27: 'All Other Returns' threshold $197,300,
        phase-in range amount $247,300."""
        assert pack.get("qbi.threshold.single").value == D(197_300)
        assert pack.get("qbi.phase_in_range_top.single").value == D(247_300)

    def test_niit_statutory(self, pack):
        """IRC §1411: 3.8% on the lesser-of, $200,000 single MAGI threshold
        (statutory, not inflation-adjusted)."""
        assert pack.get("niit.rate").value == D("0.038")
        assert pack.get("niit.magi_threshold.single").value == D(200_000)

    def test_additional_medicare_statutory(self, pack):
        """IRC §3101(b)(2): 0.9% above $200,000 (single)."""
        assert pack.get("additional_medicare.rate").value == D("0.009")
        assert pack.get("additional_medicare.threshold.single").value == D(200_000)

    def test_amt_exemption_single(self, pack):
        """Rev. Proc. 2024-40 §2.11: exemption $88,100 (Unmarried
        Individuals); phaseout threshold $626,350."""
        assert pack.get("amt.exemption.single").value == D(88_100)
        assert pack.get("amt.exemption_phaseout_threshold.single").value == D(626_350)

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
            assert (
                "Rev. Proc. 2024-40" in src
                or "IRC §" in src
                or "Instructions for Schedule A" in src
            ), f"citation not anchored to a primary document: {src!r}"
