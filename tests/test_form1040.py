"""End-to-end 1040 assembly against the TY2025 pack (synthetic inputs)."""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from telos.engine import Form1040Inputs, assemble_1040
from telos.models import W2, FilingStatus, Form1099Div, Form1099Int
from telos.params import load_pack

D = Decimal
PACK = load_pack(Path(__file__).parent.parent / "params" / "ty2025.yaml")


def mini_return(**overrides):
    base = dict(
        filing_status=FilingStatus.SINGLE,
        w2s=(W2(employer="Acme", wages=D(90_000), federal_income_tax_withheld=D(10_000)),),
        forms_1099_int=(Form1099Int(payer="Bank", interest_income=D(500)),),
        forms_1099_div=(
            Form1099Div(
                payer="Broker",
                ordinary_dividends=D(2_000),
                qualified_dividends=D(1_500),
            ),
        ),
        estimated_payments=D(1_000),
    )
    base.update(overrides)
    return Form1040Inputs(**base)


class TestEndToEnd:
    def test_mini_return_hand_computed(self):
        """Wages 90,000 + interest 500 + ordinary div 2,000 = total income
        92,500 = AGI. Standard deduction 15,750 -> taxable 76,750.
        QD 1,500 > 0 -> QDCGT: L5=75,250; L9=0 (L7=L8=48,350); L17=1,500;
        L18=225; L22=table(75,250)=round(5,578.50+.22*(75,275-48,475))=11,475;
        L23=11,700; L24=table(76,750)=round(5,578.50+.22*(76,775-48,475))=11,805;
        L25=11,700. Payments=10,000+1,000=11,000 -> balance due 700."""
        r = assemble_1040(mini_return(), PACK)
        assert r.lines["9"].value == D(92_500)
        assert r.lines["15"].value == D(76_750)
        assert r.lines["16"].value == D(11_700)
        assert r.total_payments.value == D(11_000)
        assert r.balance_due.value == D(700)

    def test_no_preferential_income_skips_qdcgt(self):
        r = assemble_1040(
            mini_return(forms_1099_div=(), forms_1099_int=()),
            PACK,
        )
        assert r.qdcgt is None
        assert "Tax Table" in r.lines["16"].sources[0]

    def test_capital_loss_reduces_income_but_no_qdcgt_gain(self):
        """Line 7 = -3,000 (loss year): total income falls, QDCGT still runs
        on QD alone with net capital gain 0."""
        r = assemble_1040(mini_return(capital_gain_line7=D(-3_000)), PACK)
        assert r.lines["9"].value == D(89_500)
        assert r.qdcgt is not None
        assert r.qdcgt.lines[3].value == D(0)

    def test_schedule_1_income_flows_to_total(self):
        r = assemble_1040(mini_return(schedule_1_income=D(12_000)), PACK)
        assert r.lines["8"].value == D(12_000)
        assert r.lines["9"].value == D(104_500)

    def test_itemized_deduction_overrides_standard(self):
        r = assemble_1040(mini_return(itemized_deduction=D(22_000)), PACK)
        assert r.lines["12"].value == D(22_000)
        assert "Schedule A" in r.lines["12"].sources[0]

    def test_other_taxes_add_to_total(self):
        r = assemble_1040(
            mini_return(other_taxes=(("form8960:NIIT", D(1_234)),)), PACK
        )
        assert r.total_tax.value == r.lines["16"].value + D(1_234)

    def test_refund_when_overwithheld(self):
        r = assemble_1040(mini_return(estimated_payments=D(5_000)), PACK)
        assert r.balance_due.value < 0

    def test_taxable_income_floors_at_zero(self):
        r = assemble_1040(
            mini_return(
                w2s=(W2(employer="Tiny", wages=D(5_000)),),
                forms_1099_int=(),
                forms_1099_div=(),
                estimated_payments=D(0),
            ),
            PACK,
        )
        assert r.lines["15"].value == D(0)
        assert r.total_tax.value == D(0)

    def test_withholding_aggregates_all_documents(self):
        r = assemble_1040(
            mini_return(
                forms_1099_int=(
                    Form1099Int(
                        payer="Bank",
                        interest_income=D(500),
                        federal_income_tax_withheld=D(50),
                    ),
                ),
            ),
            PACK,
        )
        assert r.lines["25"].value == D(10_050)


class TestExplainAndGuards:
    def test_explain_renders_full_derivation_with_citations(self):
        text = assemble_1040(mini_return(), PACK).explain()
        assert "w2:Acme.wages = 90000" in text
        assert "standard deduction" in text
        assert "OBBBA" in text  # the deduction's pack citation rides through
        assert "1040:line16" in text

    def test_unknown_input_field_rejected(self):
        with pytest.raises(ValidationError):
            Form1040Inputs(filing_status=FilingStatus.SINGLE, wages_total=D(1))

    def test_negative_estimated_payments_rejected(self):
        with pytest.raises(ValidationError):
            mini_return(estimated_payments=D(-1))

    def test_qdcgt_net_capital_gain_cannot_be_negative(self):
        with pytest.raises(ValidationError):
            mini_return(qdcgt_net_capital_gain=D(-1))
