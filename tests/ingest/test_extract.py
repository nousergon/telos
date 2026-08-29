"""Acceptance tests for the W-2 ingestion path (no network — mocked client)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from telos.ingest import (
    CrossFootError,
    ExtractedW2,
    ExtractionUnavailable,
    build_w2_request,
    extract_w2,
)
from telos.ingest.extract import _decimal_fields, outbound_payload_json
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
    """The OUTBOUND payload (system + redacted user content) contains NO SSN
    (Closes-when #2). Mock client so no network call happens; assert on the
    exact request the code would send."""
    client = MockClient(w2_tool_input())
    text = synthetic_w2_text()
    assert FAKE_SSN in text  # sanity: the SSN is present pre-redaction

    extract_w2(text, client=client)

    sent = client.last_request
    assert sent is not None
    payload = json.dumps(sent, default=str)
    assert FAKE_SSN not in payload
    assert "123456789" not in payload  # bare-digit form either
    assert "[REDACTED]" in payload


def test_pdf_attachment_raises_extraction_unavailable():
    """Vision/document (PDF) attachment is a named, tracked capability gap —
    krepis's router-edge transport has no documented multimodal contract and
    the fleet registry declares no `vision` capability tag to route on (see
    src/telos/ingest/extract.py's module docstring). Requesting it raises
    rather than silently dropping the attachment or hand-rolling an unrouted
    call — the exact failure mode this migration removes."""
    pdf = synthetic_w2_pdf()
    with pytest.raises(ExtractionUnavailable, match="not supported"):
        build_w2_request(synthetic_w2_text(), pdf_bytes=pdf)
    with pytest.raises(ExtractionUnavailable, match="not supported"):
        extract_w2(synthetic_w2_text(), pdf_bytes=pdf)


def test_build_w2_request_carries_no_ssn():
    """`build_w2_request`'s own returned dict (what `extract_w2` sends and
    what `outbound_payload_json` audits) holds no SSN — Closes-when #2's
    other half, independent of the mocked client."""
    text = synthetic_w2_text()
    request, redaction = build_w2_request(text)
    payload = outbound_payload_json(request)
    assert FAKE_SSN not in payload
    assert "[REDACTED]" in payload
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


def test_decimal_fields_drops_empty_and_none():
    raw = {"employer": "X", "wages": "1", "medicare_wages": "", "medicare_tax_withheld": None}
    out = _decimal_fields(raw)
    assert out == {"employer": "X", "wages": "1"}


def test_extract_w2_wraps_llm_config_error(monkeypatch):
    """A router/config failure surfaces as ExtractionUnavailable, never a bare
    krepis exception — the contract callers (and telos-ops) depend on."""
    from krepis.llm_config import LLMConfigError

    class _BrokenClient:
        def structured(self, **_kw):
            raise LLMConfigError("boom")

    with pytest.raises(ExtractionUnavailable, match="config error"):
        extract_w2(synthetic_w2_text(), client=_BrokenClient())


def test_extract_w2_wraps_llm_error(monkeypatch):
    from krepis.llm import LLMError

    class _FailingClient:
        def structured(self, **_kw):
            raise LLMError("no usable response")

    with pytest.raises(ExtractionUnavailable, match="did not return a usable"):
        extract_w2(synthetic_w2_text(), client=_FailingClient())


# --------------------------------------------------------------------------- #
# _resolve_spec / router fail-closed contract (2026-08-29 migration): the
# no-override path resolves via resolve_group_spec(ROUTER_GROUP) and refuses
# any route outside {litellm_proxy, egress_proxy} — mirrors
# flow_doctor.core.router.resolve_router_edge / COMPELLED_ROUTES. This is the
# specific regression this migration fixes: before it, this module built
# anthropic.Anthropic() directly with no router call at all.
# --------------------------------------------------------------------------- #
def test_resolve_spec_uses_router_group_high(monkeypatch):
    from dataclasses import dataclass

    import krepis.router as router_mod

    from telos.ingest.extract import ROUTER_GROUP, _resolve_spec

    assert ROUTER_GROUP == "high"

    @dataclass
    class _FakeSpec:
        provider: str = "litellm_proxy"
        model: str = "test-model"

    calls: dict = {}

    def _fake_resolve_group_spec(group, **kw):
        calls["group"] = group
        return _FakeSpec(), {"route": "litellm_proxy"}

    monkeypatch.setattr(router_mod, "resolve_group_spec", _fake_resolve_group_spec)
    spec = _resolve_spec()
    assert calls["group"] == ROUTER_GROUP
    assert spec.provider == "litellm_proxy"


def test_resolve_spec_fails_closed_on_noncompelled_route(monkeypatch):
    from dataclasses import dataclass

    import krepis.router as router_mod

    from telos.ingest.extract import RouterUnresolvable, _resolve_spec

    @dataclass
    class _FakeSpec:
        provider: str = "anthropic"
        model: str = "claude-opus-4-8"

    monkeypatch.setattr(
        router_mod,
        "resolve_group_spec",
        lambda group, **kw: (_FakeSpec(), {"route": "direct"}),
    )
    with pytest.raises(RouterUnresolvable, match="not a compelled path"):
        _resolve_spec()


def test_extract_w2_wraps_router_unresolvable(monkeypatch):
    """No `client=` override: the production path resolves the router and
    fails closed the same way, surfaced as ExtractionUnavailable."""
    import krepis.router as router_mod

    def _boom(group, **kw):
        raise RuntimeError("router unreachable")

    monkeypatch.setattr(router_mod, "resolve_group_spec", _boom)
    with pytest.raises(ExtractionUnavailable, match="router config error"):
        extract_w2(synthetic_w2_text())


def test_extracted_w2_forbids_extra_field():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExtractedW2(employer="X", wages=Decimal(1), bogus=Decimal(1))
