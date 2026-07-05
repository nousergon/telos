"""Form 1040-ES quarterly vouchers — safe-harbor selection + the 150k/110% fork."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from telos.contracts import EstimatedTaxRequest, estimated_tax_request_json_schema
from telos.engine.estimated import (
    compute_annualized_installments,
    compute_estimated_tax,
)
from telos.models import FilingStatus
from telos.params import load_pack

D = Decimal
ROOT = Path(__file__).parent.parent
PACK = load_pack(ROOT / "params" / "ty2025.yaml")


def request(**overrides):
    base = dict(
        filing_status=FilingStatus.SINGLE,
        prior_year_tax=D(10_000),
        prior_year_agi=D(100_000),
        current_year_projected_tax=D(20_000),
        current_year_withholding=D(0),
    )
    base.update(overrides)
    return EstimatedTaxRequest(**base)


class TestContract:
    def test_committed_schema_artifact_matches_model(self):
        committed = json.loads(
            (ROOT / "contracts" / "estimated_tax_request.schema.json").read_text()
        )
        assert committed == json.loads(
            json.dumps(estimated_tax_request_json_schema(), sort_keys=True)
        ), "contracts/estimated_tax_request.schema.json drifted — regenerate"

    def test_metron_shaped_call(self):
        """The docstring example: Metron builds the request from plain data only —
        no import from telos.engine, no ParamPack/Traced construction on its side."""
        req = EstimatedTaxRequest(
            filing_status=FilingStatus.MARRIED_FILING_JOINTLY,
            prior_year_tax=D("18500.00"),
            prior_year_agi=D("210000.00"),
            current_year_projected_tax=D("24000.00"),
            current_year_withholding=D("9000.00"),
        )
        result = compute_estimated_tax(req, PACK, tax_year=2025)
        assert result.safe_harbor_basis == "110pct_prior_year"
        assert len(result.vouchers) == 4

    def test_rejects_unknown_field(self):
        with pytest.raises(ValidationError):
            EstimatedTaxRequest(
                filing_status=FilingStatus.SINGLE,
                prior_year_tax=D(0),
                prior_year_agi=D(0),
                current_year_projected_tax=D(0),
                unexpected_field=1,
            )


class TestSafeHarborSelection:
    def test_standard_100pct_prior_year_wins(self):
        """AGI <= 150k: 100% of a 10,000 prior-year tax (10,000) is smaller
        than 90% of a 20,000 current-year projection (18,000)."""
        r = compute_estimated_tax(request(), PACK, tax_year=2025)
        assert r.safe_harbor_basis == "100pct_prior_year"
        assert r.required_annual_payment.value == D(10_000)
        assert r.total_estimated_tax_due.value == D(10_000)

    def test_110pct_fork_when_prior_year_agi_above_threshold(self):
        r = compute_estimated_tax(
            request(prior_year_agi=D(200_000), current_year_projected_tax=D(50_000)),
            PACK, tax_year=2025,
        )
        assert r.safe_harbor_basis == "110pct_prior_year"
        assert r.required_annual_payment.value == D(11_000)  # 110% * 10,000

    def test_110pct_fork_boundary_exactly_at_threshold_stays_100pct(self):
        """AGI == 150,000 exactly is NOT 'more than $150,000' (§6654(d)(1)(C)(i))."""
        r = compute_estimated_tax(
            request(prior_year_agi=D(150_000), current_year_projected_tax=D(50_000)),
            PACK, tax_year=2025,
        )
        assert r.safe_harbor_basis == "100pct_prior_year"

    def test_mfs_higher_income_threshold_is_halved(self):
        r_below = compute_estimated_tax(
            request(
                filing_status=FilingStatus.MARRIED_FILING_SEPARATELY,
                prior_year_agi=D(75_000), current_year_projected_tax=D(50_000),
            ),
            PACK, tax_year=2025,
        )
        assert r_below.safe_harbor_basis == "100pct_prior_year"

        r_above = compute_estimated_tax(
            request(
                filing_status=FilingStatus.MARRIED_FILING_SEPARATELY,
                prior_year_agi=D(75_001), current_year_projected_tax=D(50_000),
            ),
            PACK, tax_year=2025,
        )
        assert r_above.safe_harbor_basis == "110pct_prior_year"

    def test_90pct_current_year_wins_when_smaller(self):
        r = compute_estimated_tax(
            request(prior_year_tax=D(100_000), prior_year_agi=D(200_000),
                    current_year_projected_tax=D(5_000)),
            PACK, tax_year=2025,
        )
        assert r.safe_harbor_basis == "90pct_current_year"
        assert r.required_annual_payment.value == D(4_500)  # 90% * 5,000

    def test_short_prior_year_return_forces_current_year_harbor(self):
        """prior_year_return_covered_12_months=False disables the prior-year
        harbors entirely (§6654(d)(1)(B)(ii)) even though 100% of prior-year
        tax would otherwise be far cheaper."""
        r = compute_estimated_tax(
            request(prior_year_tax=D(1), prior_year_agi=D(50_000),
                    prior_year_return_covered_12_months=False,
                    current_year_projected_tax=D(20_000)),
            PACK, tax_year=2025,
        )
        assert r.safe_harbor_basis == "90pct_current_year"
        assert r.required_annual_payment.value == D(18_000)


class TestVouchers:
    def test_four_even_installments_with_statutory_due_dates(self):
        r = compute_estimated_tax(
            request(current_year_withholding=D(2_000)), PACK, tax_year=2025
        )
        assert [v.quarter for v in r.vouchers] == [1, 2, 3, 4]
        assert [v.due_date for v in r.vouchers] == [
            "2025-04-15", "2025-06-15", "2025-09-15", "2026-01-15",
        ]
        assert sum(v.amount.value for v in r.vouchers) == r.total_estimated_tax_due.value

    def test_remainder_trues_up_on_q4(self):
        r = compute_estimated_tax(
            request(prior_year_tax=D(10_001), current_year_projected_tax=D(50_000)),
            PACK, tax_year=2025,
        )
        amounts = [v.amount.value for v in r.vouchers]
        assert amounts[0] == amounts[1] == amounts[2] == D(2_500)
        assert amounts[3] == D(2_501)
        assert sum(amounts) == D(10_001)

    def test_withholding_covers_full_liability_yields_no_vouchers(self):
        r = compute_estimated_tax(
            request(current_year_withholding=D(50_000)), PACK, tax_year=2025
        )
        assert r.total_estimated_tax_due.value == D(0)
        assert r.vouchers == ()

    def test_explain_renders_provenance(self):
        r = compute_estimated_tax(
            request(current_year_withholding=D(1_000)), PACK, tax_year=2025
        )
        text = r.explain()
        assert "estimated:total_estimated_tax_due" in text
        assert "Q1 due 2025-04-15" in text


class TestAnnualizedIncomeMethod:
    """Schedule AI (§6654(d)(2)) — telos-ops#20."""

    def test_requires_period_income_when_method_requested(self):
        with pytest.raises(ValidationError):
            request(use_annualized_income_method=True)

    def test_period_income_must_be_non_decreasing(self):
        with pytest.raises(ValidationError):
            request(
                use_annualized_income_method=True,
                annualized_period_taxable_income=(D(50_000), D(40_000), D(80_000), D(120_000)),
            )

    def test_period_income_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            request(
                use_annualized_income_method=True,
                annualized_period_taxable_income=(D(-1), D(40_000), D(80_000), D(120_000)),
            )

    def test_even_income_reproduces_even_installments(self):
        """PROPERTY: income arriving ratably must annualize to the same four
        even installments the safe-harbor (even-installment) method produces —
        the annualized method may only ever *lower* a penalty, never raise a
        voucher above the plain 25% installment for smooth income."""
        # 90%-of-current-year harbor governs here: prior-year tax is huge.
        # Ratable income of 120k/yr = 10k/month; the §6654 annualization
        # periods END at months 3, 5, 8, 12 (NOT 3/6/9/12), so ratable
        # cumulative taxable income is 30k / 50k / 80k / 120k.
        full_year = D(120_000)
        cumulative = (D(30_000), D(50_000), D(80_000), full_year)  # exactly ratable
        annualized_req = request(
            prior_year_tax=D(1_000_000),
            current_year_projected_tax=D(20_000),
            use_annualized_income_method=True,
            annualized_period_taxable_income=cumulative,
        )
        even_req = request(
            prior_year_tax=D(1_000_000), current_year_projected_tax=D(20_000)
        )
        r_ann = compute_estimated_tax(annualized_req, PACK, tax_year=2025)
        r_even = compute_estimated_tax(even_req, PACK, tax_year=2025)
        assert [v.amount.value for v in r_ann.vouchers] == [
            v.amount.value for v in r_even.vouchers
        ]

    @pytest.mark.parametrize(
        "cumulative",
        [
            (D(0), D(0), D(0), D(120_000)),  # all income in Q4
            (D(120_000), D(120_000), D(120_000), D(120_000)),  # all income in Q1
            (D(10_000), D(25_000), D(90_000), D(120_000)),  # lumpy
        ],
    )
    def test_annualized_vouchers_never_exceed_total_and_sum_to_it(self, cumulative):
        req = request(
            prior_year_tax=D(1_000_000),
            current_year_projected_tax=D(20_000),
            use_annualized_income_method=True,
            annualized_period_taxable_income=cumulative,
        )
        r = compute_estimated_tax(req, PACK, tax_year=2025)
        assert sum(v.amount.value for v in r.vouchers) == r.total_estimated_tax_due.value
        assert all(v.amount.value >= 0 for v in r.vouchers)

    def test_backloaded_income_defers_early_installments(self):
        """Income all in Q4 -> the first three annualized installments are 0
        (nothing has been earned yet), the whole requirement lands on Q4."""
        req = request(
            prior_year_tax=D(1_000_000),
            current_year_projected_tax=D(20_000),
            use_annualized_income_method=True,
            annualized_period_taxable_income=(D(0), D(0), D(0), D(120_000)),
        )
        r = compute_estimated_tax(req, PACK, tax_year=2025)
        amounts = [v.amount.value for v in r.vouchers]
        assert amounts[0] == amounts[1] == amounts[2] == D(0)
        assert amounts[3] == r.total_estimated_tax_due.value

    def test_installment_worksheet_factors_and_percentages(self):
        brackets = PACK.brackets("ordinary_brackets.single")
        res = compute_annualized_installments(
            (D(30_000), D(50_000), D(80_000), D(120_000)), brackets
        )
        factors = [i.annualization_factor.value for i in res.installments]
        pcts = [i.applicable_percentage.value for i in res.installments]
        assert factors == [D(4), D("2.4"), D("1.5"), D(1)]
        assert pcts == [D("0.225"), D("0.45"), D("0.675"), D("0.90")]
        # provenance carries the statute cite
        cites = res.installments[0].required_installment.all_sources()
        assert any("6654(d)(2)" in s for s in cites)
        assert "annualized:required_installment_q1" in res.explain()

    def test_zero_annualized_income_defers_everything_to_the_final_trueup(self):
        """A degenerate all-zero annualized-income input (share denominator 0)
        leaves the first three installments at 0; the harbor still exists (it
        rides on projected tax, not annualized income), so its whole amount
        trues up on the final installment."""
        req = request(
            prior_year_tax=D(1_000_000),
            current_year_projected_tax=D(20_000),
            use_annualized_income_method=True,
            annualized_period_taxable_income=(D(0), D(0), D(0), D(0)),
        )
        r = compute_estimated_tax(req, PACK, tax_year=2025)
        amounts = [v.amount.value for v in r.vouchers]
        assert amounts[:3] == [D(0), D(0), D(0)]
        assert amounts[3] == r.total_estimated_tax_due.value

    def test_withholding_covers_liability_yields_no_annualized_vouchers(self):
        req = request(
            prior_year_tax=D(1_000_000),
            current_year_projected_tax=D(20_000),
            current_year_withholding=D(50_000),
            use_annualized_income_method=True,
            annualized_period_taxable_income=(D(30_000), D(50_000), D(80_000), D(120_000)),
        )
        r = compute_estimated_tax(req, PACK, tax_year=2025)
        assert r.vouchers == ()


class TestRetainedError:
    def test_error_still_importable_and_raisable(self):
        from telos.engine.estimated import AnnualizedIncomeMethodNotImplementedError

        with pytest.raises(AnnualizedIncomeMethodNotImplementedError):
            raise AnnualizedIncomeMethodNotImplementedError("edge sub-case")
