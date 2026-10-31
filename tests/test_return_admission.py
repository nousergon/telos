"""Full-return dispatch and admission at the engine boundary (telos-ops#49, telos-ops#50).

Every case runs through each full-return entry point: ``compute_federal_return`` (the
direct API), ``run_replay`` (the replay harness) and, where the inputs fit a planning
scenario, ``project``. All figures are synthetic worked examples. None comes from a
real return.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from telos.contracts import Form8949Box, RealizedLot, RealizedLots, Term
from telos.engine import MissingMedicareWagesError, ScheduleDInputs, schedule_d
from telos.engine.amt_guard import AmtReviewRequired
from telos.models import W2, FilingStatus
from telos.orchestrate import FullReturnInputs, TaxYearMismatchError, compute_federal_return
from telos.params import load_pack
from telos.planning import PlanningScenario, project
from telos.replay import ReplayFixture, run_replay

D = Decimal
ROOT = Path(__file__).parent.parent
PACK_2025 = load_pack(ROOT / "params" / "ty2025.yaml")


def _w2(wages, box6=None, **fields):
    return W2(
        employer="SYNTH",
        wages=D(wages),
        medicare_wages=fields.pop("medicare_wages", D(wages)),
        medicare_tax_withheld=(
            D(box6) if box6 is not None else (D(wages) * D("0.0145")).quantize(D("0.01"))
        ),
        **fields,
    )


def _inputs(**overrides):
    base = dict(tax_year=2025, filing_status=FilingStatus.SINGLE, w2s=(_w2(60_000),))
    base.update(overrides)
    return FullReturnInputs(**base)


def _replay(inputs):
    """The replay entry point; the golden is a throwaway, the comparison is the
    computed value, which this reads back."""
    report = run_replay(ReplayFixture(federal=inputs, golden={"agi": D(0)}), PACK_2025)
    return report.rows[0].computed


def _lot(proceeds, cost, term):
    return RealizedLot(
        description="SYNTH",
        date_acquired="2024-01-02",
        date_sold="2025-06-02",
        proceeds=D(proceeds),
        cost_basis=D(cost),
        term=term,
        box=Form8949Box.A if term is Term.SHORT else Form8949Box.D,
        source="synthetic",
    )


# ── telos-ops#49: carryovers are capital activity on their own ──────────────


@pytest.mark.parametrize("lots", [None, RealizedLots()], ids=["omitted", "explicit-empty"])
def test_st_carryover_worked_example_is_independent_of_the_lots_container(lots):
    fed = compute_federal_return(_inputs(st_loss_carryover=D(5_000), realized_lots=lots), PACK_2025)

    assert fed.result.lines["7"].value == D(-3_000)
    assert fed.result.lines["11"].value == D(57_000)
    assert fed.result.lines["16"].value == D(4_715)
    assert _replay(_inputs(st_loss_carryover=D(5_000), realized_lots=lots)) == D(57_000)


@pytest.mark.parametrize("lots", [None, RealizedLots()], ids=["omitted", "explicit-empty"])
def test_lt_carryover_alone_reaches_schedule_d(lots):
    fed = compute_federal_return(_inputs(lt_loss_carryover=D(5_000), realized_lots=lots), PACK_2025)

    assert fed.schedule_d is not None
    assert fed.result.lines["7"].value == D(-3_000)


def test_mfs_loss_cap_applies_to_a_carryover_only_return():
    # The full return refuses MFS at the AMT guard (not calibrated), so the cap is
    # checked on the Schedule D the orchestrator now dispatches for a carryover alone.
    sched = schedule_d(
        ScheduleDInputs(
            filing_status=FilingStatus.MARRIED_FILING_SEPARATELY,
            realized=RealizedLots(),
            st_loss_carryover=D(5_000),
        )
    )

    assert sched.line7a.value == D(-1_500)
    with pytest.raises(AmtReviewRequired):
        compute_federal_return(
            _inputs(
                filing_status=FilingStatus.MARRIED_FILING_SEPARATELY, st_loss_carryover=D(5_000)
            ),
            PACK_2025,
        )


def test_mixed_gain_and_carryover_net_on_schedule_d():
    fed = compute_federal_return(
        _inputs(
            realized_lots=RealizedLots(lots=(_lot(12_000, 10_000, Term.SHORT),)),
            lt_loss_carryover=D(5_000),
        ),
        PACK_2025,
    )

    assert fed.result.lines["7"].value == D(-3_000)


def test_zero_activity_returns_match_with_and_without_an_empty_container():
    omitted = compute_federal_return(_inputs(), PACK_2025)
    explicit = compute_federal_return(_inputs(realized_lots=RealizedLots()), PACK_2025)

    assert omitted.schedule_d is None
    assert omitted.result.lines["7"].value == explicit.result.lines["7"].value == D(0)
    assert omitted.result.total_tax.value == explicit.result.total_tax.value


def test_planning_carries_a_carryover_without_manufacturing_lots():
    scenario = PlanningScenario(
        tax_year=2025,
        as_of="2025-07-01",
        filing_status=FilingStatus.SINGLE,
        w2s=(_w2(60_000),),
        st_loss_carryover=D(5_000),
        prior_year_agi=D(60_000),
        prior_year_tax=D(5_000),
    )

    assert project(scenario, PACK_2025).artifact.projected.agi == D(57_000)


# ── telos-ops#50: admission ─────────────────────────────────────────────────


def test_wrong_year_pack_is_refused_before_any_return_is_built():
    inputs = _inputs(tax_year=2024)

    with pytest.raises(TaxYearMismatchError, match=r"TY2024.*TY2025"):
        compute_federal_return(inputs, PACK_2025)
    with pytest.raises(TaxYearMismatchError):
        _replay(inputs)


@pytest.mark.parametrize(
    "w2s",
    [
        (W2(employer="SYNTH", wages=D(220_000)),),
        (_w2(100_000), W2(employer="OTHER", wages=D(120_000))),
        (W2(employer="SYNTH", wages=D(220_000), medicare_wages=D(220_000)),),
    ],
    ids=["all-missing", "mixed-complete-incomplete", "box6-only-missing"],
)
def test_missing_medicare_boxes_are_refused_not_zeroed(w2s):
    with pytest.raises(MissingMedicareWagesError):
        compute_federal_return(_inputs(w2s=w2s), PACK_2025)
    with pytest.raises(MissingMedicareWagesError):
        _replay(_inputs(w2s=w2s))


def test_complete_high_wage_return_carries_additional_medicare_tax():
    fed = compute_federal_return(_inputs(w2s=(_w2(220_000, box6=3_190),)), PACK_2025)

    assert fed.f8959 is not None
    assert fed.f8959.additional_medicare_tax.value == D(180)
    assert fed.result.total_tax.value == D(42_603)


def test_complete_low_wage_return_has_no_additional_tax_or_credit():
    fed = compute_federal_return(_inputs(), PACK_2025)

    assert fed.f8959 is not None
    assert fed.f8959.additional_medicare_tax.value == D(0)
    assert fed.f8959.additional_withholding.value == D(0)


def test_additional_medicare_withholding_is_credited():
    # Box 6 = 1.45% of 220,000 plus the employer's 0.9% on the 20,000 over 200,000.
    fed = compute_federal_return(_inputs(w2s=(_w2(220_000, box6=3_370),)), PACK_2025)

    assert fed.f8959.additional_withholding.value == D(180)
    assert fed.result.total_tax.value == D(42_603)


def test_no_w2_return_needs_no_form_8959():
    fed = compute_federal_return(_inputs(w2s=()), PACK_2025)

    assert fed.f8959 is None
