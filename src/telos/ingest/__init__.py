"""Document ingestion layer.

LLM extraction lives HERE, never in ``telos.engine`` (the engine is pure
deterministic arithmetic). Flow: redact identities before any API call →
krepis router-edge tool-use structured extraction → cross-foot against the
document's own totals → human-confirm loop with freeze-with-hash and
corrected-document re-ingest.

Routing addresses a krepis router model_group (a capability tier), never a
model id or provider — see ``telos.ingest.extract.ROUTER_GROUP`` and its
module docstring for the 2026-08-29 krepis-router migration.
"""

from __future__ import annotations

from telos.ingest.confirm import (
    FieldView,
    FrozenExtraction,
    content_hash,
    freeze,
    reingest_correction,
    side_by_side,
)
from telos.ingest.extract import (
    ExtractionUnavailable,
    RouterUnresolvable,
    W2ExtractionResult,
    build_w2_request,
    extract_w2,
)
from telos.ingest.prompt_loader import PromptNotFoundError, load_prompt
from telos.ingest.redaction import (
    REDACTION_TOKEN,
    RedactionResult,
    assert_no_ssn,
    redact,
)
from telos.ingest.schema import (
    CrossFootError,
    ExtractedConsolidated1099,
    ExtractedW2,
    cross_foot_w2,
)

__all__ = [
    "REDACTION_TOKEN",
    "CrossFootError",
    "ExtractedConsolidated1099",
    "ExtractedW2",
    "ExtractionUnavailable",
    "FieldView",
    "FrozenExtraction",
    "PromptNotFoundError",
    "RedactionResult",
    "RouterUnresolvable",
    "W2ExtractionResult",
    "assert_no_ssn",
    "build_w2_request",
    "content_hash",
    "cross_foot_w2",
    "extract_w2",
    "freeze",
    "load_prompt",
    "redact",
    "reingest_correction",
    "side_by_side",
]
