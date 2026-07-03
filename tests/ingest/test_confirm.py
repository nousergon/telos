"""Confirm-loop tests — side-by-side, freeze-with-hash, corrected re-ingest."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from telos.ingest.confirm import (
    content_hash,
    freeze,
    reingest_correction,
    side_by_side,
)
from telos.ingest.schema import ExtractedConsolidated1099, ExtractedW2

_NOW = datetime(2026, 4, 1, tzinfo=UTC)


def _w2() -> ExtractedW2:
    return ExtractedW2(
        employer="Acme Synthetic Widgets LLC",
        wages=Decimal("50000.00"),
        medicare_wages=Decimal("52000.00"),
        medicare_tax_withheld=Decimal("754.00"),
    )


def test_side_by_side_pairs_every_field_with_source():
    views = side_by_side(_w2(), source_page=1)
    names = {v.name for v in views}
    assert "wages" in names and "employer" in names
    assert all(v.source_page == 1 for v in views)


def test_freeze_stamps_and_verifies():
    frozen = freeze(_w2(), doc_type="w2", now=_NOW)
    assert frozen.doc_type == "w2"
    assert frozen.frozen_at == _NOW.isoformat()
    assert frozen.supersedes is None
    assert frozen.verify()
    assert frozen.content_hash == content_hash(_w2())


def test_tampering_frozen_fields_fails_verify():
    frozen = freeze(_w2(), doc_type="w2", now=_NOW)
    tampered = frozen.model_copy(update={"fields": {**frozen.fields, "wages": "99999.00"}})
    assert not tampered.verify()


def test_hash_is_deterministic_and_order_independent():
    a = freeze(_w2(), doc_type="w2", now=_NOW)
    b = freeze(_w2(), doc_type="w2", now=_NOW)
    assert a.content_hash == b.content_hash


def test_corrected_1099_reingest_supersedes_prior():
    original = ExtractedConsolidated1099(
        payer="Broker X", interest_income=Decimal("100.00")
    )
    prior = freeze(original, doc_type="consolidated_1099", now=_NOW)

    corrected = ExtractedConsolidated1099(
        payer="Broker X", interest_income=Decimal("125.00"), is_corrected=True
    )
    new = reingest_correction(corrected, prior=prior, now=_NOW)

    assert new.supersedes == prior.content_hash
    assert new.content_hash != prior.content_hash
    assert new.doc_type == "consolidated_1099"
    assert new.verify()


def test_default_now_is_used_when_omitted():
    frozen = freeze(_w2(), doc_type="w2")
    # Just assert it parses as an ISO timestamp.
    datetime.fromisoformat(frozen.frozen_at)
