"""Shared fixtures for ingestion tests — a mock Anthropic client (no network)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class _ToolUseBlock:
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class _Response:
    content: list[Any]


class MockMessages:
    """Records the outbound request and returns a canned tool_use response."""

    def __init__(self, tool_input: dict[str, Any]) -> None:
        self._tool_input = tool_input
        self.last_request: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> _Response:
        self.last_request = kwargs
        return _Response(content=[_ToolUseBlock(input=dict(self._tool_input))])


class MockClient:
    """Mock ``anthropic.Anthropic()`` — asserts no real network call is made."""

    def __init__(self, tool_input: dict[str, Any]) -> None:
        self.messages = MockMessages(tool_input)


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
