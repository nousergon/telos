"""Acceptance tests for the W-2 ingestion path (no network — mocked client)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from telos.ingest import (
    CrossFootError,
    ExtractedW2,
    build_w2_request,
    extract_w2,
)
from telos.ingest.extract import _decimal_fields, _tool_input, outbound_payload_json
from telos.models import W2

from .conftest import MockClient, w2_tool_input
from .synthetic_w2 import FAKE_SSN, synthetic_w2_pdf, synthetic_w2_text


def test_synthetic_w2_extracts_to_validated_model():
    """A SYNTHETIC W-2 extracts to a validated W2 model (Closes-when #1)."""
    client = MockClient(w2_tool_input())
    result = extract_w2(synthetic_w2_text(), client=client)

    assert isinstance(result.extracted, ExtractedW2)
    assert result.extracted.wages == Decimal("50000.00")
    assert result.extracted.employer == "Acme Synthetic Widgets LLC"

    # Projects to the canonical engine model.
    engine_w2 = result.extracted.to_w2()
    assert isinstance(engine_w2, W2)
    assert engine_w2.medicare_wages == Decimal("52000.00")

    # SSN was re-joined LOCALLY, never via the model/API.
    assert result.ssn == FAKE_SSN

    # The result convenience accessor returns the extracted model.
    assert result.to_w2() is result.extracted


def test_outbound_payload_contains_no_ssn():
    """The OUTBOUND API payload contains NO SSN (Closes-when #2).

    Mock client so no network call happens; assert on the exact request the code
    would send.
    """
    client = MockClient(w2_tool_input())
    text = synthetic_w2_text()
    assert FAKE_SSN in text  # sanity: the SSN is present pre-redaction

    extract_w2(text, client=client)

    sent = client.messages.last_request
    assert sent is not None
    payload = json.dumps(sent, default=str)
    assert FAKE_SSN not in payload
    assert "123456789" not in payload  # bare-digit form either
    assert "[REDACTED]" in payload


def test_outbound_pdf_payload_carries_no_ssn():
    """When a synthetic PDF is attached, the request still holds no SSN."""
    pdf = synthetic_w2_pdf()
    request, redaction = build_w2_request(synthetic_w2_text(), pdf_bytes=pdf)

    assert request["messages"][0]["content"][0]["type"] == "document"
    assert FAKE_SSN not in outbound_payload_json(request)
    assert redaction.ssns == [FAKE_SSN]


def test_cross_foot_failure_raises_on_tampered_doc():
    """A tampered synthetic doc RAISES on cross-foot (Closes-when #3)."""
    # Box 4 tampered so it no longer equals 6.2% of Box 3.
    client = MockClient(w2_tool_input(social_security_tax_withheld="9999.00"))
    with pytest.raises(CrossFootError, match="Box 4"):
        extract_w2(synthetic_w2_text(tampered=True), client=client)


def test_medicare_cross_foot_failure_raises():
    client = MockClient(w2_tool_input(medicare_tax_withheld="1234.00"))
    with pytest.raises(CrossFootError, match="Box 6"):
        extract_w2(synthetic_w2_text(), client=client)


def test_tool_input_missing_block_raises():
    class _Empty:
        content: tuple = ()

    with pytest.raises(ValueError, match="no tool_use block"):
        _tool_input(_Empty())


def test_decimal_fields_drops_empty_and_none():
    raw = {"employer": "X", "wages": "1", "medicare_wages": "", "medicare_tax_withheld": None}
    out = _decimal_fields(raw)
    assert out == {"employer": "X", "wages": "1"}


def test_default_client_lazy_import(monkeypatch):
    """A missing/blank client triggers the lazy anthropic import path."""

    class _FakeAnthropic:
        def __init__(self, *a, **k):
            self.messages = MockClient(w2_tool_input()).messages

    class _FakeModule:
        Anthropic = _FakeAnthropic

    monkeypatch.setitem(__import__("sys").modules, "anthropic", _FakeModule)
    result = extract_w2(synthetic_w2_text())
    assert result.extracted.wages == Decimal("50000.00")


def test_extracted_w2_forbids_extra_field():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExtractedW2(employer="X", wages=Decimal(1), bogus=Decimal(1))
