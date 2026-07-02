from decimal import Decimal

import pytest
from pydantic import ValidationError

from telos.models import W2, FilingStatus, Form1099Div, Form1099Int

D = Decimal


class TestW2:
    def test_valid(self):
        w2 = W2(employer="Acme", wages=D("50000.25"), federal_income_tax_withheld=D(8000))
        assert w2.wages == D("50000.25")

    def test_withholding_defaults_zero(self):
        assert W2(employer="Acme", wages=D(1)).federal_income_tax_withheld == D(0)

    def test_negative_wages_rejected(self):
        with pytest.raises(ValidationError):
            W2(employer="Acme", wages=D(-1))

    def test_unknown_field_rejected(self):
        # extra="forbid" is the model-layer coverage guard
        with pytest.raises(ValidationError):
            W2(employer="Acme", wages=D(1), dependent_care_benefits=D(5000))

    def test_frozen(self):
        w2 = W2(employer="Acme", wages=D(1))
        with pytest.raises(ValidationError):
            w2.wages = D(2)


class TestForm1099Div:
    def test_qualified_subset_of_ordinary_ok(self):
        f = Form1099Div(payer="Broker", ordinary_dividends=D(100), qualified_dividends=D(80))
        assert f.qualified_dividends == D(80)

    def test_qualified_exceeding_ordinary_rejected(self):
        with pytest.raises(ValidationError, match="subset"):
            Form1099Div(payer="Broker", ordinary_dividends=D(100), qualified_dividends=D(101))

    def test_qualified_equal_ordinary_ok(self):
        Form1099Div(payer="Broker", ordinary_dividends=D(100), qualified_dividends=D(100))


class TestForm1099Int:
    def test_valid(self):
        f = Form1099Int(payer="Bank", interest_income=D("12.34"))
        assert f.interest_income == D("12.34")


class TestFilingStatus:
    def test_all_five_statuses_exist(self):
        assert len(FilingStatus) == 5

    def test_string_valued(self):
        assert FilingStatus.SINGLE.value == "single"
