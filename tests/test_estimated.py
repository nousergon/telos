"""Form 1040-ES quarterly vouchers — safe-harbor selection + the 150k/110% fork."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from telos.contracts import EstimatedTaxRequest, estimated_tax_request_json_schema
from telos.engine.estimated import (
    AnnualizedIncomeMethodNotImplementedError,
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


class TestAnnualizedIncomeMethodStub:
    def test_requesting_annualized_method_raises_not_silently_falls_back(self):
        with pytest.raises(AnnualizedIncomeMethodNotImplementedError):
            compute_estimated_tax(
                request(use_annualized_income_method=True), PACK, tax_year=2025
            )
