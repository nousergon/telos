"""telos.planning: scenario -> projection -> payment flags.

The anchor case is fully hand-computed against the TY2026 pack's cited
values (Rev. Proc. 2025-32) so the projection path has an independent
arithmetic check, not just internal consistency.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from telos.contracts import (
    LossRegime,
    QuarterPaymentStatus,
    RentalArrangement,
    ScheduleEWorksheet,
    tax_projection_json_schema,
)
from telos.models import W2, FilingStatus
from telos.params import load_pack
from telos.planning import EstimatedPaymentMade, PlanningScenario, project

D = Decimal
ROOT = Path(__file__).parent.parent
PACK_2026 = load_pack(ROOT / "params" / "ty2026.yaml")
PACK_2025 = load_pack(ROOT / "params" / "ty2025.yaml")
OH_PACK_2026 = load_pack(ROOT / "params" / "ty2026_oh.yaml")
WA_PACK_2025 = load_pack(ROOT / "params" / "ty2025_wa.yaml")


def duplex_schedule_e(tax_year=2026, net_income=None):
    """Synthetic Ohio-source rental duplex (telos-ops#21)."""
    return ScheduleEWorksheet(
        tax_year=tax_year,
        arrangements=(
            RentalArrangement(
                arrangement_id="oh-duplex",
                property_name="Columbus duplex",
                regime=LossRegime.SECTION_469_PASSIVE,
                net_income_post_caps=net_income if net_income is not None else D(4_000),
                source="manual:synthetic-planning-scenario",
            ),
        ),
    )


def scenario(**overrides) -> PlanningScenario:
    base = dict(
        tax_year=2026,
        as_of="2026-07-01",
        filing_status=FilingStatus.SINGLE,
        w2s=(W2(employer="SYNTH", wages=D(100_000), federal_income_tax_withheld=D(8_000)),),
        prior_year_agi=D(90_000),
        prior_year_tax=D(13_000),
    )
    base.update(overrides)
    return PlanningScenario(**base)


@pytest.fixture(scope="module")
def outcome():
    return project(scenario(), PACK_2026)


class TestHandComputedAnchor:
    """Single, wages $100,000, withholding $8,000, nothing else, TY2026.

    taxable = 100,000 - 16,100 (Rev. Proc. 2025-32 §4.14) = 83,900
    line 16 = Tax Table semantics: bin [83,900, 83,950) midpoint 83,925
            = 5,800 + 0.22 * (83,925 - 50,400)   [§4.01 Table 3]
            = 13,175.50 -> 13,176
    90% harbor = 11,858.40 -> 11,858; 100% prior harbor = 13,000
    required = 11,858 (current-year, smaller); due = 11,858 - 8,000 = 3,858
    vouchers = 965 / 965 / 965 / 963
    """

    def test_projected_liability(self, outcome):
        p = outcome.artifact.projected
        assert p.agi == D(100_000)
        assert p.taxable_income == D(83_900)
        assert p.total_tax == D(13_176)
        assert p.total_withholding == D(8_000)
        assert p.balance_due == D(13_176) - D(8_000)
        assert p.marginal_ordinary_rate == D("0.22")
        assert p.effective_rate_on_agi == D("0.1318")  # 13,176 / 100,000

    def test_safe_harbor_current_year_binds(self, outcome):
        sh = outcome.artifact.safe_harbor
        assert sh.basis == "90pct_current_year"
        assert sh.required_annual_payment == D(11_858)
        assert sh.total_estimated_tax_due == D(3_858)

    def test_vouchers_true_up_on_q4(self, outcome):
        amounts = [q.required for q in outcome.artifact.quarters]
        assert amounts == [D(965), D(965), D(965), D(963)]
        assert sum(amounts) == outcome.artifact.safe_harbor.total_estimated_tax_due

    def test_quarter_statuses_against_as_of(self, outcome):
        """as_of 2026-07-01: Q1 (4/15) and Q2 (6/15) past, unpaid -> OVERDUE;
        Q3 (9/15) and Q4 (1/15/27) -> UPCOMING."""
        statuses = [q.status for q in outcome.artifact.quarters]
        assert statuses == [
            QuarterPaymentStatus.OVERDUE,
            QuarterPaymentStatus.OVERDUE,
            QuarterPaymentStatus.UPCOMING,
            QuarterPaymentStatus.UPCOMING,
        ]

    def test_headline_catch_up(self, outcome):
        h = outcome.artifact.headline
        assert h.payment_recommended
        assert h.recommended_amount == D(965) + D(965) + D(965)  # Q1+Q2 overdue + Q3 next
        assert h.next_due_date == "2026-09-15"

    def test_artifact_carries_pack_status(self, outcome):
        assert outcome.artifact.pack_status == "provisional"


class TestPaymentsAndHarborForks:
    def test_paid_quarters_flag_paid_and_shrink_headline(self):
        outcome = project(
            scenario(
                estimated_payments_made=(
                    EstimatedPaymentMade(quarter=1, date_paid="2026-04-10", amount=D(965)),
                    EstimatedPaymentMade(quarter=2, date_paid="2026-06-10", amount=D(965)),
                )
            ),
            PACK_2026,
        )
        statuses = [q.status for q in outcome.artifact.quarters]
        assert statuses[:2] == [QuarterPaymentStatus.PAID, QuarterPaymentStatus.PAID]
        assert outcome.artifact.headline.recommended_amount == D(965)  # Q3 only
        assert outcome.artifact.projected.estimated_payments_made == D(1_930)

    def test_withholding_meets_harbor_no_vouchers(self):
        outcome = project(
            scenario(
                w2s=(
                    W2(
                        employer="SYNTH",
                        wages=D(100_000),
                        federal_income_tax_withheld=D(20_000),
                    ),
                )
            ),
            PACK_2026,
        )
        assert outcome.artifact.quarters == ()
        assert not outcome.artifact.headline.payment_recommended
        assert outcome.artifact.safe_harbor.total_estimated_tax_due == D(0)

    def test_higher_income_prior_year_fork_110pct(self):
        """Prior AGI > $150k and a small prior-year tax -> the 110% prior-year
        harbor undercuts 90%-of-current and binds."""
        outcome = project(
            scenario(prior_year_agi=D(200_000), prior_year_tax=D(1_000)),
            PACK_2026,
        )
        sh = outcome.artifact.safe_harbor
        assert sh.basis == "110pct_prior_year"
        assert sh.required_annual_payment == D(1_100)

    def test_aggregate_gains_ride_schedule_d_and_qdcgt(self):
        """LT gain taxed preferentially: total tax must be LESS than the same
        amount as wages, and MORE than without the gain at all."""
        base = project(scenario(), PACK_2026).artifact.projected.total_tax
        with_lt = project(scenario(lt_net_gain=D(50_000)), PACK_2026)
        as_wages = project(
            scenario(
                w2s=(
                    W2(
                        employer="SYNTH",
                        wages=D(150_000),
                        federal_income_tax_withheld=D(8_000),
                    ),
                )
            ),
            PACK_2026,
        )
        lt_tax = with_lt.artifact.projected.total_tax
        assert base < lt_tax < as_wages.artifact.projected.total_tax
        assert with_lt.artifact.projected.agi == D(150_000)

    def test_projection_monotonic_in_wages(self):
        taxes = [
            project(
                scenario(w2s=(W2(employer="SYNTH", wages=D(w)),)), PACK_2026
            ).artifact.projected.total_tax
            for w in (50_000, 150_000, 400_000)
        ]
        assert taxes == sorted(taxes)
        assert len(set(taxes)) == 3


class TestGuards:
    def test_pack_year_mismatch_raises(self):
        with pytest.raises(ValueError, match=r"TY2026.*TY2025"):
            project(scenario(), PACK_2025)

    def test_as_of_must_be_iso_date(self):
        with pytest.raises(ValueError, match="ISO date"):
            scenario(as_of="July 1, 2026")

    def test_payment_date_must_be_iso(self):
        with pytest.raises(ValueError, match="ISO date"):
            EstimatedPaymentMade(quarter=1, date_paid="04/10/2026", amount=D(100))


class TestCliAndReport:
    def test_cli_renders_report_and_writes_artifact(self, tmp_path, capsys):
        from telos.planning.__main__ import main

        scenario_yaml = tmp_path / "scenario.yaml"
        scenario_yaml.write_text(
            "\n".join(
                [
                    'schema_version: "1.0.0"',
                    "tax_year: 2026",
                    'as_of: "2026-07-01"',
                    "filing_status: single",
                    "w2s:",
                    '  - employer: "SYNTH"',
                    '    wages: "100000"',
                    '    federal_income_tax_withheld: "8000"',
                    'prior_year_agi: "90000"',
                    'prior_year_tax: "13000"',
                ]
            )
        )
        out = tmp_path / "proj.json"
        rc = main(
            [
                str(scenario_yaml),
                "--pack",
                str(ROOT / "params" / "ty2026.yaml"),
                "--out",
                str(out),
            ]
        )
        assert rc == 0
        report = capsys.readouterr().out
        assert "Telos tax projection — TY2026" in report
        assert "Q3 due 2026-09-15" in report
        written = json.loads(out.read_text())
        assert written["schema_version"] == "1.1.0"
        assert written["headline"]["payment_recommended"] is True
        # optional state sections omitted entirely when no state pack is
        # given to the CLI — additive/backward-compatible per schema 1.1.0.
        assert written["wa"] is None
        assert written["ohio"] is None


class TestArtifactContract:
    def test_committed_schema_matches_generated(self):
        committed = json.loads(
            (ROOT / "contracts" / "tax_projection.schema.json").read_text()
        )
        assert committed == tax_projection_json_schema(), (
            "contracts/tax_projection.schema.json drifted — regenerate from the models"
        )

    def test_artifact_round_trips_as_json(self):
        from telos.contracts import TaxProjection

        outcome = project(scenario(), PACK_2026)
        raw = outcome.artifact.model_dump_json()
        assert TaxProjection.model_validate_json(raw) == outcome.artifact

    def test_wa_and_ohio_sections_absent_by_default(self):
        """Extension point is opt-in: omitting wa_pack/oh_pack leaves both
        sections None — no behavior change for existing callers (telos-ops#21)."""
        outcome = project(scenario(), PACK_2026)
        assert outcome.artifact.wa is None
        assert outcome.artifact.ohio is None


class TestStateExtensionSections:
    """telos-ops#21: WA excise exposure + OH nonresident liability, wired
    through the SAME planning scenario -> projection path as the federal
    numbers, each with citations even when the answer is negative."""

    def test_wa_excise_not_applicable_shows_computation(self):
        """Small LT gain, well under WA's $278,000 standard deduction —
        NOT applicable, but the computation is still shown (checkers cite
        their work)."""
        outcome = project(
            scenario(lt_net_gain=D(50_000)), PACK_2026, wa_pack=WA_PACK_2025
        )
        wa = outcome.artifact.wa
        assert wa is not None
        assert wa.applicable is False
        assert wa.tax == D(0)
        assert wa.wa_allocable_long_term_gain == D(50_000)
        assert "278000" in wa.citations[0] or any("278000" in c for c in wa.citations)
        assert wa.message  # non-empty: the determination + computation

    def test_wa_excise_applicable_computes_tax(self):
        """300,000 LT gain (below the AMT-screen trigger zone): taxable
        22,000 -> 7% = 1,540."""
        outcome = project(
            scenario(lt_net_gain=D(300_000)), PACK_2026, wa_pack=WA_PACK_2025
        )
        wa = outcome.artifact.wa
        assert wa.applicable is True
        assert wa.taxable_gain == D(22_000)
        assert wa.tax == D(1_540)
        assert wa.citations

    def test_ohio_duplex_section_emits_liability_and_estimated_advisory(self):
        outcome = project(
            scenario(schedule_e=duplex_schedule_e()),
            PACK_2026,
            oh_pack=OH_PACK_2026,
        )
        oh = outcome.artifact.ohio
        assert oh is not None
        assert oh.filing_required is True
        assert oh.net_tax >= D(0)
        assert oh.citations
        assert "OH net tax" in oh.message

    def test_ohio_section_without_prior_year_uses_90pct_current_year(self):
        outcome = project(
            scenario(schedule_e=duplex_schedule_e(net_income=D(50_000))),
            PACK_2026,
            oh_pack=OH_PACK_2026,
        )
        oh = outcome.artifact.ohio
        assert oh.required_annual_payment == round(oh.net_tax * D("0.9"))

    def test_ohio_section_uses_lesser_of_prior_and_current_harbor(self):
        outcome = project(
            scenario(
                schedule_e=duplex_schedule_e(net_income=D(50_000)),
                prior_year_oh_tax=D(10),
            ),
            PACK_2026,
            oh_pack=OH_PACK_2026,
        )
        oh = outcome.artifact.ohio
        assert oh.required_annual_payment == D(10)
        assert oh.estimated_payments_advisable is False  # 10 <= $500 de minimis

    def test_both_sections_present_together(self):
        """The closes-when scenario: LT gains + duplex Schedule E emits
        BOTH state sections in one projection run."""
        outcome = project(
            scenario(lt_net_gain=D(300_000), schedule_e=duplex_schedule_e()),
            PACK_2026,
            wa_pack=WA_PACK_2025,
            oh_pack=OH_PACK_2026,
        )
        assert outcome.artifact.wa is not None
        assert outcome.artifact.ohio is not None
        assert outcome.artifact.wa.applicable is True
        assert outcome.artifact.ohio.filing_required is True

    def test_no_schedule_e_still_emits_ohio_section_not_required(self):
        """Opting into oh_pack without any Ohio-source income still shows
        the determination (not required) rather than omitting the section."""
        outcome = project(scenario(), PACK_2026, oh_pack=OH_PACK_2026)
        oh = outcome.artifact.ohio
        assert oh is not None
        assert oh.filing_required is False
        assert oh.net_tax == D(0)
