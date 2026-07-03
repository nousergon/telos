"""TY2024 parameter-pack verification.

Same transcription cross-check as ``test_ty2025_pack.py``: each Rev. Proc.
2023-34 §3.01 rate-table row prints the cumulative tax at the bracket's lower
boundary ("$5,426 plus 22% of the excess over $47,150"); ``tax_from_brackets``
evaluated exactly at every boundary must reproduce those printed constants,
validating BOTH the boundaries and the rates of the transcription
simultaneously.

The pack is `final`: values and form-level structure are transcribed from the
published final 2024 documents (Rev. Proc. 2023-34; 2024 Form 1040
instructions). This CI test is NON-personal. The end-to-end golden replay of
the filed TY2024 return (``pytest -m personal``, telos-ops#18) needs a
filed-2024 fixture that lives outside the repo and never runs in CI.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from telos.engine import marginal_rate, tax_from_brackets
from telos.params import load_pack

D = Decimal
PACK_PATH = Path(__file__).parent.parent / "params" / "ty2024.yaml"


@pytest.fixture(scope="module")
def pack():
    return load_pack(PACK_PATH)


class TestPackLoads:
    def test_loads_as_final(self, pack):
        assert pack.tax_year == 2024
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


# Printed cumulative constants from Rev. Proc. 2023-34 §3.01, quoted verbatim
# from the tables ("The Tax Is: $X plus R% of the excess over $B"). Keyed by
# (filing_status, boundary) -> printed constant at that boundary.
REV_PROC_CONSTANTS = {
    # Table 3 — Unmarried Individuals: "$1,160 plus 12% ... over $11,600";
    # "$5,426 plus 22% ... over $47,150"; "$17,168.50 plus 24% ... over
    # $100,525"; "$39,110.50 plus 32% ... over $191,950"; "$55,678.50 plus
    # 35% ... over $243,725"; "$183,647.25 plus 37% ... over $609,350".
    "single": [
        (11_600, "1160"),
        (47_150, "5426"),
        (100_525, "17168.50"),
        (191_950, "39110.50"),
        (243_725, "55678.50"),
        (609_350, "183647.25"),
    ],
    # Table 1 — MFJ/QSS: "$2,320 plus 12% ... over $23,200"; "$10,852 plus
    # 22% ... over $94,300"; "$34,337 plus 24% ... over $201,050"; "$78,221
    # plus 32% ... over $383,900"; "$111,357 plus 35% ... over $487,450";
    # "$196,669.50 plus 37% ... over $731,200".
    "married_filing_jointly": [
        (23_200, "2320"),
        (94_300, "10852"),
        (201_050, "34337"),
        (383_900, "78221"),
        (487_450, "111357"),
        (731_200, "196669.50"),
    ],
    # Table 2 — HOH: "$1,655 plus 12% ... over $16,550"; "$7,241 plus 22% ...
    # over $63,100"; "$15,469 plus 24% ... over $100,500"; "$37,417 plus 32%
    # ... over $191,950"; "$53,977 plus 35% ... over $243,700"; "$181,954.50
    # plus 37% ... over $609,350".
    "head_of_household": [
        (16_550, "1655"),
        (63_100, "7241"),
        (100_500, "15469"),
        (191_950, "37417"),
        (243_700, "53977"),
        (609_350, "181954.50"),
    ],
    # Table 4 — MFS: same rows as single through $243,725, then "$55,678.50
    # plus 35% ... over $243,725" capped at $365,600: "$98,334.75 plus 37% ...
    # over $365,600".
    "married_filing_separately": [
        (11_600, "1160"),
        (47_150, "5426"),
        (100_525, "17168.50"),
        (191_950, "39110.50"),
        (243_725, "55678.50"),
        (365_600, "98334.75"),
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
                f"Rev. Proc. 2023-34 prints {printed}"
            )

    def test_top_marginal_rate_is_37pct_everywhere(self, pack):
        for fs in REV_PROC_CONSTANTS:
            assert marginal_rate(D(10_000_000), pack.brackets(f"ordinary_brackets.{fs}")) == D(
                "0.37"
            )


# The 2024 Tax Computation Worksheet (2024 Form 1040 instructions) prints each
# high-income row as "multiply by rate, then subtract this amount". Each row's
# subtraction amount is exactly rate*boundary - cumulative_tax_at_boundary, so
# it reproduces the bracket formula — the reason ``tax_lookup`` computes the
# TCW as ``tax_from_brackets`` and needs no per-year constants (telos-ops#18
# item 3). Verified here against the values PRINTED on the 2024 TCW.
TCW_SUBTRACTION_AMOUNTS = {
    # Section A (Single): rows over $100,000.
    "single": [
        ("0.22", 100_525, "4947.00"),
        ("0.24", 191_950, "6957.50"),
        ("0.32", 243_725, "22313.50"),
        ("0.35", 609_350, "29625.25"),
        ("0.37", 609_350, "41812.25"),
    ],
    # Section B (MFJ/QSS): rows over $100,000.
    "married_filing_jointly": [
        ("0.22", 201_050, "9894.00"),
        ("0.24", 383_900, "13915.00"),
        ("0.32", 487_450, "44627.00"),
        ("0.35", 731_200, "59250.50"),
        ("0.37", 731_200, "73874.50"),
    ],
}


class TestTaxComputationWorksheetSubtractionConstants:
    @pytest.mark.parametrize("filing_status", sorted(TCW_SUBTRACTION_AMOUNTS))
    def test_printed_tcw_subtraction_amounts_are_bracket_algebra(self, pack, filing_status):
        """For every printed 2024 TCW row, rate*boundary minus the pack's
        cumulative bracket tax at that boundary equals the printed subtraction
        amount — i.e. ``rate*x - subtraction`` IS ``tax_from_brackets(x)`` on
        that row, so the engine's algebraic TCW reproduces the printed form."""
        schedule = pack.brackets(f"ordinary_brackets.{filing_status}")
        for rate, boundary, printed_sub in TCW_SUBTRACTION_AMOUNTS[filing_status]:
            cumulative = tax_from_brackets(D(boundary), schedule)
            derived_sub = D(rate) * D(boundary) - cumulative
            assert derived_sub == D(printed_sub), (
                f"{filing_status} {rate} row @ {boundary}: derived subtraction "
                f"{derived_sub}, 2024 TCW prints {printed_sub}"
            )


class TestSpotChecksAgainstCitedDocuments:
    def test_standard_deduction_pre_obbba(self, pack):
        """Rev. Proc. 2023-34 §3.15(1): $14,600 single/MFS, $29,200 MFJ/QSS,
        $21,900 HOH — the pre-OBBBA amounts (2025's $15,750 does NOT apply)."""
        assert pack.get("standard_deduction.single").value == D(14_600)
        assert pack.get("standard_deduction.married_filing_jointly").value == D(29_200)
        assert pack.get("standard_deduction.head_of_household").value == D(21_900)

    def test_ltcg_breakpoints_single(self, pack):
        """Rev. Proc. 2023-34 §3.03: 'All Other Individuals' Maximum Zero Rate
        Amount $47,025; Maximum 15% Rate Amount $518,900 (also QDCGT worksheet
        lines 6 and 13)."""
        assert pack.get("ltcg.zero_rate_max.single").value == D(47_025)
        assert pack.get("ltcg.fifteen_rate_max.single").value == D(518_900)

    def test_salt_cap_is_flat_10000_pre_obbba(self, pack):
        """TY2024 predates OBBBA §70120: the flat $10,000 ($5,000 MFS)
        §164(b)(6) cap with NO MAGI phase-down (the phase-down keys the 2025
        pack carries simply do not exist for 2024)."""
        assert pack.get("salt.cap").value == D(10_000)
        assert pack.get("salt.cap_married_filing_separately").value == D(5_000)
        assert "salt" not in pack.values or "phase_down_rate" not in pack.values["salt"]

    def test_qbi_threshold_single(self, pack):
        """Rev. Proc. 2023-34 §3.27: 'All Other Returns' threshold $191,950,
        phase-in range amount $241,950."""
        assert pack.get("qbi.threshold.single").value == D(191_950)
        assert pack.get("qbi.phase_in_range_top.single").value == D(241_950)

    def test_niit_statutory(self, pack):
        assert pack.get("niit.rate").value == D("0.038")
        assert pack.get("niit.magi_threshold.single").value == D(200_000)

    def test_additional_medicare_statutory(self, pack):
        assert pack.get("additional_medicare.rate").value == D("0.009")
        assert pack.get("additional_medicare.threshold.single").value == D(200_000)

    def test_amt_exemption_and_25pct_phaseout(self, pack):
        """Rev. Proc. 2023-34 §3.11: exemption $85,700 (unmarried), threshold
        $609,350; the 25% pre-OBBBA phaseout rate must reproduce the printed
        complete-phaseout amounts: $952,150 = $609,350 + $85,700/0.25
        (unmarried) and $1,751,900 = $1,218,700 + $133,300/0.25 (joint)."""
        exemption = pack.get("amt.exemption.single").value
        threshold = pack.get("amt.exemption_phaseout_threshold.single").value
        rate = pack.get("amt.exemption_phaseout_rate").value
        assert exemption == D(85_700)
        assert threshold == D(609_350)
        assert rate == D("0.25")
        assert threshold + exemption / rate == D(952_150)
        mfj_exemption = pack.get("amt.exemption.married_filing_jointly").value
        mfj_threshold = pack.get(
            "amt.exemption_phaseout_threshold.married_filing_jointly"
        ).value
        assert mfj_threshold + mfj_exemption / rate == D(1_751_900)

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
                "Rev. Proc. 2023-34" in src
                or "IRC §" in src
                or "Instructions for Schedule A" in src
            ), f"citation not anchored to a primary document: {src!r}"
