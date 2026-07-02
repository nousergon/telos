"""The coverage guard: silence is impossible.

A tax engine that is 98% right is worthless — the failure mode is silent
omission (a form box the pipeline didn't recognize, quietly dropped from the
return). The guard makes the engine's supported universe explicit and turns
every gap into a hard, named failure instead of a smaller refund or an
underreported liability.

Policy (plan §5.3): an unrecognized *document type* always fails; an
unrecognized *field* fails when it carries a meaningful (non-zero, non-empty)
value — a zero or empty unknown field is ignorable noise, a non-zero one is
money the engine would silently drop.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any


class CoverageError(Exception):
    """Base: the input universe exceeded what the engine declares it supports."""


class UnsupportedDocumentError(CoverageError):
    def __init__(self, doc_type: str, supported: tuple[str, ...]) -> None:
        self.doc_type = doc_type
        super().__init__(
            f"unsupported document type {doc_type!r}; this engine supports: "
            f"{', '.join(supported) or '(none)'}. Refusing to continue — an "
            f"ignored document is a silent omission from the return."
        )


class UnsupportedFieldError(CoverageError):
    def __init__(self, doc_type: str, field: str, value: Any) -> None:
        self.doc_type = doc_type
        self.field = field
        super().__init__(
            f"document {doc_type!r} carries unsupported field {field!r} with "
            f"non-zero value {value!r}. Refusing to continue — dropping it "
            f"would silently misstate the return. Add the field to the "
            f"engine's coverage (and its handling) or correct the input."
        )


def _is_meaningful(value: Any) -> bool:
    """True when dropping the value would change the return."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return value != 0
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return False
        try:
            return Decimal(stripped) != 0
        except InvalidOperation:
            return True  # non-numeric text (e.g. a code) is meaningful
    return True  # unknown container types: assume meaningful, fail loud


class CoverageGuard:
    """Declares the supported universe of document types and their fields."""

    def __init__(self, documents: Mapping[str, frozenset[str] | set[str]]) -> None:
        if not documents:
            raise ValueError("CoverageGuard requires at least one supported document type")
        self._documents = {dt: frozenset(fields) for dt, fields in documents.items()}

    @property
    def supported_documents(self) -> tuple[str, ...]:
        return tuple(sorted(self._documents))

    def check_document(self, doc_type: str) -> None:
        if doc_type not in self._documents:
            raise UnsupportedDocumentError(doc_type, self.supported_documents)

    def check_fields(self, doc_type: str, fields: Mapping[str, Any]) -> None:
        """Hard-fail on any unknown field carrying a meaningful value."""
        self.check_document(doc_type)
        supported = self._documents[doc_type]
        for name, value in fields.items():
            if name not in supported and _is_meaningful(value):
                raise UnsupportedFieldError(doc_type, name, value)
