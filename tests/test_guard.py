from decimal import Decimal

import pytest

from telos.engine import CoverageGuard, UnsupportedDocumentError, UnsupportedFieldError

GUARD = CoverageGuard(
    {
        "w2": {"wages", "federal_income_tax_withheld"},
        "1099-int": {"interest_income"},
    }
)


class TestDocuments:
    def test_supported_document_passes(self):
        GUARD.check_document("w2")

    def test_unknown_document_fails_loud(self):
        with pytest.raises(UnsupportedDocumentError, match="1099-b"):
            GUARD.check_document("1099-b")

    def test_error_names_the_supported_universe(self):
        with pytest.raises(UnsupportedDocumentError, match="w2"):
            GUARD.check_document("k-1")

    def test_empty_guard_rejected(self):
        with pytest.raises(ValueError, match="at least one"):
            CoverageGuard({})


class TestFields:
    def test_known_fields_pass(self):
        GUARD.check_fields("w2", {"wages": Decimal(100), "federal_income_tax_withheld": 0})

    def test_unknown_field_with_value_fails(self):
        with pytest.raises(UnsupportedFieldError, match="dependent_care_benefits"):
            GUARD.check_fields("w2", {"wages": 1, "dependent_care_benefits": Decimal(5000)})

    def test_unknown_field_zero_is_ignored(self):
        GUARD.check_fields("w2", {"wages": 1, "dependent_care_benefits": Decimal(0)})

    def test_unknown_field_none_is_ignored(self):
        GUARD.check_fields("w2", {"wages": 1, "dependent_care_benefits": None})

    def test_unknown_field_empty_string_is_ignored(self):
        GUARD.check_fields("w2", {"wages": 1, "box14_other": "  "})

    def test_unknown_field_numeric_string_zero_is_ignored(self):
        GUARD.check_fields("w2", {"wages": 1, "box12a": "0.00"})

    def test_unknown_field_nonzero_string_fails(self):
        with pytest.raises(UnsupportedFieldError):
            GUARD.check_fields("w2", {"wages": 1, "box12a": "1500.00"})

    def test_unknown_field_code_string_fails(self):
        # non-numeric text (a W-2 box 12 code) is meaningful
        with pytest.raises(UnsupportedFieldError):
            GUARD.check_fields("w2", {"wages": 1, "box12a_code": "DD"})

    def test_unknown_true_bool_fails(self):
        with pytest.raises(UnsupportedFieldError):
            GUARD.check_fields("w2", {"wages": 1, "statutory_employee": True})

    def test_unknown_false_bool_ignored(self):
        GUARD.check_fields("w2", {"wages": 1, "statutory_employee": False})

    def test_fields_on_unknown_document_fail_on_document_first(self):
        with pytest.raises(UnsupportedDocumentError):
            GUARD.check_fields("k-1", {"anything": 1})
