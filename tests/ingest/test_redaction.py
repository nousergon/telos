"""Redaction tests — the SSN/EIN/account never survives outbound."""

from __future__ import annotations

import pytest

from telos.ingest.redaction import REDACTION_TOKEN, assert_no_ssn, redact

from .synthetic_w2 import FAKE_EIN, FAKE_SSN, synthetic_w2_text


def test_redacts_ssn_ein_account_from_synthetic_w2():
    result = redact(synthetic_w2_text())
    assert FAKE_SSN not in result.text
    assert FAKE_EIN not in result.text
    assert REDACTION_TOKEN in result.text
    assert result.ssns == [FAKE_SSN]
    assert result.contains_any_identifier()


def test_redacts_bare_nine_digit_ssn():
    result = redact("SSN 123456789 and wages 50000.00")
    assert "123456789" not in result.text
    # A money amount with a decimal is not treated as an account number.
    assert "50000.00" in result.text


def test_label_rule_catches_masked_ssn():
    result = redact("Employee's social security number: XXX-XX-1234")
    assert "XXX-XX-1234" not in result.text
    assert "ssn" in result.identifiers


def test_ein_label_and_account_label():
    result = redact(
        "Employer identification number: 98-7654321\nAccount no. AB12CD34EF56"
    )
    assert "98-7654321" not in result.text
    assert "AB12CD34EF56" not in result.text
    assert "ein" in result.identifiers
    assert "account" in result.identifiers


def test_assert_no_ssn_raises_when_ssn_present():
    with pytest.raises(ValueError, match="SSN"):
        assert_no_ssn("leaked 123-45-6789 here")


def test_assert_no_ssn_passes_on_clean_text():
    # Must not raise on clean text.
    assert_no_ssn("wages 50000.00 all clean")


def test_bare_long_digit_run_redacted_as_account():
    # A 10+ digit run with no label still gets caught by the generic account rule.
    result = redact("reference 0123456789012 on statement")
    assert "0123456789012" not in result.text
    assert result.identifiers["account"] == ["0123456789012"]


def test_clean_text_has_no_identifiers():
    result = redact("just wages 50000.00 and interest 12.34")
    assert not result.contains_any_identifier()
    assert result.ssns == []
