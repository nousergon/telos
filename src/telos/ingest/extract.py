"""Claude vision + tool-use extraction.

This is the ONLY module in ``telos`` that talks to an LLM, and it lives in
``src/telos/ingest/`` — never in ``src/telos/engine/`` (the engine is pure
deterministic arithmetic). The Anthropic SDK is imported lazily so the rest of
the ingest package (redaction, schema, prompt loading) imports with no network
dependency.

The outbound request is built so it provably carries no SSN:

1. the source page is rendered/OCR'd to text upstream,
2. :func:`telos.ingest.redaction.redact` strips SSN/EIN/account values,
3. :func:`telos.ingest.redaction.assert_no_ssn` guards the exact string sent,
4. only then is the request handed to the client.

Structured output uses tool-use with ``strict: true`` so the model's tool
input validates exactly against the W-2 box schema.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Protocol

from telos.ingest.prompt_loader import load_prompt
from telos.ingest.redaction import RedactionResult, assert_no_ssn, redact
from telos.ingest.schema import ExtractedW2, cross_foot_w2

# Default to a current model; do NOT hardcode a stale id. Overridable per call.
DEFAULT_MODEL = "claude-opus-4-8"

_W2_TOOL: dict[str, Any] = {
    "name": "record_w2",
    "description": "Record the transcribed money boxes of a single IRS Form W-2.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "employer": {"type": "string"},
            "wages": {"type": "string", "description": "Box 1 as a decimal string"},
            "federal_income_tax_withheld": {"type": "string", "description": "Box 2"},
            "social_security_wages": {"type": "string", "description": "Box 3"},
            "social_security_tax_withheld": {"type": "string", "description": "Box 4"},
            "medicare_wages": {"type": "string", "description": "Box 5"},
            "medicare_tax_withheld": {"type": "string", "description": "Box 6"},
        },
        "required": ["employer", "wages"],
        "additionalProperties": False,
    },
}


class SupportsMessages(Protocol):
    """Minimal shape of ``anthropic.Anthropic().messages`` used here.

    Declared as a Protocol so tests inject a mock client with no network and no
    hard dependency on the ``anthropic`` package being importable.
    """

    def create(self, **kwargs: Any) -> Any: ...


class AnthropicClientLike(Protocol):
    messages: SupportsMessages


def _default_client() -> AnthropicClientLike:
    import anthropic  # lazy — never imported at package import time

    return anthropic.Anthropic()


def _tool_input(response: Any) -> dict[str, Any]:
    """Pull the single ``record_w2`` tool_use input out of a Messages response."""
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            return dict(block.input)
    raise ValueError("model returned no tool_use block; cannot extract structured W-2")


def _decimal_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce the tool's decimal-string fields, dropping omitted/empty ones."""
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key == "employer":
            out[key] = value
        elif value in (None, ""):
            continue
        else:
            out[key] = value
    return out


class W2ExtractionResult:
    """Extracted, cross-footed W-2 plus the locally-held redacted identity."""

    def __init__(self, extracted: ExtractedW2, redaction: RedactionResult) -> None:
        self.extracted = extracted
        self.redaction = redaction

    @property
    def ssn(self) -> str | None:
        ssns = self.redaction.ssns
        return ssns[0] if ssns else None

    def to_w2(self) -> ExtractedW2:
        return self.extracted


def build_w2_request(
    source_text: str,
    *,
    model: str = DEFAULT_MODEL,
    pdf_bytes: bytes | None = None,
    max_tokens: int = 1024,
) -> tuple[dict[str, Any], RedactionResult]:
    """Build the outbound Messages request, redacting first and asserting no SSN.

    ``source_text`` is the OCR/extracted page text (may contain an SSN on entry);
    it is redacted here. ``pdf_bytes``, if given, is attached as a document block
    — callers should only pass pre-redacted image/PDF bytes; the SSN guard covers
    the text channel.
    """
    redaction = redact(source_text)
    assert_no_ssn(redaction.text)

    content: list[dict[str, Any]] = []
    if pdf_bytes is not None:
        content.append(
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(pdf_bytes).decode("ascii"),
                },
            }
        )
    content.append(
        {
            "type": "text",
            "text": f"{load_prompt('w2_extraction')}\n\n--- REDACTED SOURCE ---\n{redaction.text}",
        }
    )

    return {
        "model": model,
        "max_tokens": max_tokens,
        "tools": [_W2_TOOL],
        "tool_choice": {"type": "tool", "name": "record_w2"},
        "messages": [{"role": "user", "content": content}],
    }, redaction


def extract_w2(
    source_text: str,
    *,
    client: AnthropicClientLike | None = None,
    model: str = DEFAULT_MODEL,
    pdf_bytes: bytes | None = None,
) -> W2ExtractionResult:
    """Redact → call Claude (vision + strict tool-use) → validate → cross-foot.

    The SSN never reaches the API: it is redacted out and re-joined locally onto
    the returned :class:`W2ExtractionResult`. Cross-foot failure raises.
    """
    request, redaction = build_w2_request(
        source_text, model=model, pdf_bytes=pdf_bytes
    )
    if client is None:
        client = _default_client()

    response = client.messages.create(**request)
    raw = _tool_input(response)
    extracted = ExtractedW2(**_decimal_fields(raw))
    cross_foot_w2(extracted)  # raises CrossFootError on mismatch
    return W2ExtractionResult(extracted=extracted, redaction=redaction)


def outbound_payload_json(request: dict[str, Any]) -> str:
    """Serialize an outbound request for auditing (used by the no-SSN test)."""
    return json.dumps(request, default=str)
