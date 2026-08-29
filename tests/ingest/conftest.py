"""Shared fixtures for ingestion tests — a mock krepis LLMClient (no network).

Since the 2026-08-29 krepis-router migration (src/telos/ingest/extract.py),
``extract_w2`` calls ``client.structured(...)`` — the krepis
``LLMClient``-shaped surface — rather than an ``anthropic.Anthropic()``
Messages client. ``MockClient`` here mirrors that surface directly (not the
retired ``anthropic`` SDK shape), so tests exercise the real call contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class _StructuredResult:
    data: dict[str, Any]


class MockClient:
    """Mock krepis ``LLMClient`` — records the outbound ``structured()``
    call and returns a canned parsed payload. Asserts no real network call
    is made (nothing here can reach one)."""

    def __init__(self, tool_input: dict[str, Any]) -> None:
        self._tool_input = tool_input
        self.last_request: dict[str, Any] | None = None

    def structured(self, **kwargs: Any) -> _StructuredResult:
        self.last_request = kwargs
        return _StructuredResult(data=dict(self._tool_input))


def w2_tool_input(**overrides: Any) -> dict[str, str]:
    """A well-formed ``record_w2`` tool input matching the synthetic W-2."""
    base = {
        "employer": "Acme Synthetic Widgets LLC",
        "wages": "50000.00",
        "federal_income_tax_withheld": "8000.00",
        "social_security_wages": "52000.00",
        "social_security_tax_withheld": "3224.00",
        "medicare_wages": "52000.00",
        "medicare_tax_withheld": "754.00",
    }
    base.update(overrides)
    return base
