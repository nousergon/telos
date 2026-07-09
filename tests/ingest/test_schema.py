"""Schema + cross-foot tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from telos.ingest.schema import (
    CrossFootError,
    ExtractedConsolidated1099,
    ExtractedW2,
    cross_foot_w2,
)


def test_cross_foot_passes_on_consistent_boxes():
    w2 = ExtractedW2(
        employer="X",
        wages=Decimal("50000.00"),
        social_security_wages=Decimal("52000.00"),
        social_security_tax_withheld=Decimal("3224.00"),
        medicare_wages=Decimal("52000.00"),
        medicare_tax_withheld=Decimal("754.00"),
    )
    assert cross_foot_w2(w2) is None


def test_cross_foot_tolerates_penny_rounding():
    w2 = ExtractedW2(
        employer="X",
        wages=Decimal("1"),
        medicare_wages=Decimal("52000.00"),
        medicare_tax_withheld=Decimal("754.01"),  # 1 cent off, within tolerance
    )
    assert cross_foot_w2(w2) is None


def test_cross_foot_skips_when_boxes_absent():
    # No SS or Medicare boxes → nothing to cross-foot, must not raise.
    w2 = ExtractedW2(employer="X", wages=Decimal("50000.00"))
    assert cross_foot_w2(w2) is None


def test_cross_foot_ss_mismatch_raises():
    w2 = ExtractedW2(
        employer="X",
        wages=Decimal("1"),
        social_security_wages=Decimal("52000.00"),
        social_security_tax_withheld=Decimal("100.00"),
    )
    with pytest.raises(CrossFootError, match="Box 4"):
        cross_foot_w2(w2)


def test_consolidated_qualified_exceeds_ordinary_raises():
    # pydantic wraps the model_validator's CrossFootError in a ValidationError.
    with pytest.raises(ValidationError, match="qualified"):
        ExtractedConsolidated1099(
            payer="B",
            ordinary_dividends=Decimal("10.00"),
            qualified_dividends=Decimal("20.00"),
        )


def test_consolidated_minimal_ok():
    doc = ExtractedConsolidated1099(payer="B", interest_income=Decimal("5.00"))
    assert doc.is_corrected is False
