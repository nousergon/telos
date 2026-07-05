"""Human-confirm loop: side-by-side view, freeze-with-hash, corrected re-ingest.

A full UI is out of scope; this models the *data flow*:

* :func:`side_by_side` pairs each extracted field with a reference to its source
  page so a reviewer sees source ↔ extraction together.
* :func:`freeze` stamps a confirmed extraction with a content hash. The hash is
  deterministic over the canonical field set, so a frozen record is
  tamper-evident — mutating any field and re-hashing yields a different digest.
* Corrected-1099 re-ingest is a first-class flow: :func:`reingest_correction`
  supersedes a prior frozen record, carrying the ``supersedes`` hash so the
  lineage from the original filing to the correction is explicit.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Optional

from pydantic import BaseModel


@dataclass(frozen=True)
class FieldView:
    """One extracted field paired with a reference to where it was read from."""

    name: str
    value: Any
    source_page: int
    source_label: str


def side_by_side(extracted: BaseModel, *, source_page: int = 1) -> list[FieldView]:
    """Produce the reviewer's source ↔ extracted-field pairing."""
    dumped = extracted.model_dump()
    return [
        FieldView(name=name, value=value, source_page=source_page, source_label=name)
        for name, value in dumped.items()
    ]


def _canonical(payload: dict[str, Any]) -> str:
    """Stable JSON: sorted keys, Decimals as strings — deterministic bytes."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(extracted: BaseModel) -> str:
    """SHA-256 over the canonical field set of an extraction."""
    return hashlib.sha256(_canonical(extracted.model_dump()).encode("utf-8")).hexdigest()


class FrozenExtraction(BaseModel):
    """An extraction a human has confirmed, stamped with a tamper-evident hash."""

    doc_type: str
    fields: dict[str, Any]
    content_hash: str
    frozen_at: str
    supersedes: Optional[str] = None  # noqa: UP045 — prior hash on a correction

    def verify(self) -> bool:
        """Recompute the hash from ``fields`` and check it matches the stamp."""
        recomputed = hashlib.sha256(_canonical(self.fields).encode("utf-8")).hexdigest()
        return recomputed == self.content_hash


def freeze(
    extracted: BaseModel,
    *,
    doc_type: str,
    supersedes: Optional[str] = None,  # noqa: UP045
    now: Optional[datetime] = None,  # noqa: UP045
) -> FrozenExtraction:
    """Freeze a confirmed extraction: snapshot fields + hash + timestamp.

    ``supersedes`` carries the prior frozen record's hash when this freeze is a
    correction, making the correction lineage explicit.
    """
    stamp = (now or datetime.now(UTC)).isoformat()
    return FrozenExtraction(
        doc_type=doc_type,
        fields=extracted.model_dump(),
        content_hash=content_hash(extracted),
        frozen_at=stamp,
        supersedes=supersedes,
    )


def reingest_correction(
    corrected: BaseModel,
    *,
    prior: FrozenExtraction,
    now: Optional[datetime] = None,  # noqa: UP045
) -> FrozenExtraction:
    """Freeze a corrected re-ingest that supersedes a prior frozen record.

    First-class corrected-1099 flow: the returned record links back to ``prior``
    via ``supersedes`` so the original and its correction are both retained.
    """
    return freeze(
        corrected,
        doc_type=prior.doc_type,
        supersedes=prior.content_hash,
        now=now,
    )
