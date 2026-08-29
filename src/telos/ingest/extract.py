"""krepis router-edge extraction: structured tool-use over a redacted source.

This is the ONLY module in ``telos`` that talks to an LLM, and it lives in
``src/telos/ingest/`` — never in ``src/telos/engine/`` (the engine is pure
deterministic arithmetic). krepis is imported lazily so the rest of the
ingest package (redaction, schema, prompt loading) imports with no network
dependency.

The outbound request is built so it provably carries no SSN:

1. the source page is rendered/OCR'd to text upstream,
2. :func:`telos.ingest.redaction.redact` strips SSN/EIN/account values,
3. :func:`telos.ingest.redaction.assert_no_ssn` guards the exact string sent,
4. only then is the request handed to the client.

Structured output uses a strict JSON-schema tool contract so the model's
response validates exactly against the W-2 box schema.

Routing (2026-08-29 migration, telos-ops-I<N>): every call funnels through
the krepis router — mirrors ``flow_doctor.core.router.resolve_router_edge``
and ``metron_ext.advisor.llm`` (the fleet's two reference patterns for this
class; see ``model-router-policy.md`` §5). This module previously
constructed ``anthropic.Anthropic()`` directly with no router, no fallback,
and no egress-proxy DLP scan at all — a hand-rolled provider-specific
request shape (Anthropic's ``tool_choice``/``tools`` wire format) with none
of the fleet's substitutability machinery. That was both a LIVE direct-
Anthropic violation (Brian's 2026-08-29 ruling: "we shouldn't be using the
anthropic api at all") and a parallel setup (his other 2026-08-29 ruling:
"it should all funnel through the krepis router ... no other parallel
setups").

**Vision/document (PDF) attachment is a named, tracked capability gap, not
silently dropped.** The prior code accepted an optional ``pdf_bytes`` and
attached it as an Anthropic-specific ``document`` content block; no
production caller ever passed one (grep confirmed: only this module's own
tests did), and krepis's public ``LLMClient.structured()``/``complete()``
surface takes a single string ``user_content`` with no documented multimodal
contract, and the fleet's ``LLM_MODEL_REGISTRY.yaml`` declares no ``vision``
capability tag a router group could select on. Rather than hand-roll an
undocumented, untested multimodal path outside the router (exactly the kind
of parallel setup this migration removes), :func:`build_w2_request` now
raises :class:`ExtractionUnavailable` when ``pdf_bytes`` is passed, naming
the gap. Tracked: telos-ops-I<N>.
"""

from __future__ import annotations

import json
from typing import Any

CALLSITE_ID = "telos-extract-w2"

# krepis router model_group this call site asks for — a CAPABILITY TIER,
# never a model id or provider (principle 8, substitutability). "high": real-
# money tax-accuracy stakes (an extraction error propagates into a filed
# figure), but not "ultra" (reserved for genuine multi-step design judgment,
# e.g. crucible-evaluator's Director). Stated assumption (2026-08-29
# migration) — revisit if extraction quality regresses relative to the prior
# claude-opus-4-8 baseline; needs a LLM_CALLSITE_REGISTRY.yaml row (out of
# scope for this repo, tracked telos-ops-I<N>).
ROUTER_GROUP = "high"

# krepis compelled routes — mirrors flow_doctor.core.router.COMPELLED_ROUTES
# and morning_signal.claude._COMPELLED_ROUTES (model-router-policy.md §5):
# the only two paths a call may be served on. Anything else means krepis's
# own fallback picked a direct provider outside the registry-derived chain,
# which alpha-engine-config-I6367 and Brian's 2026-08-29 "everything funnels
# through the krepis router" ruling both forbid.
_COMPELLED_ROUTES = frozenset({"litellm_proxy", "egress_proxy"})

_W2_SCHEMA: dict[str, Any] = {
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
}
_SCHEMA_NAME = "record_w2"


class RouterUnresolvable(RuntimeError):
    """The krepis router could not resolve ``ROUTER_GROUP`` to a callable
    endpoint on a compelled route.

    A distinct type (mirrors ``flow_doctor.core.router.RouterUnresolvable``
    and ``model-router-policy`` R20) so callers never mistake "the router
    could not be reached" for "the router was reached and declined" — this
    always means the LLM call did not happen at all.
    """


class ExtractionUnavailable(RuntimeError):
    """Raised when W-2 extraction cannot run: the router is unresolvable,
    the model config is invalid, a document/vision attachment was requested
    (not yet supported — see the module docstring), or the model failed to
    return a usable extraction."""


def _resolve_spec():
    """Resolve ``ROUTER_GROUP`` via the krepis router, fail-closed off any
    route outside :data:`_COMPELLED_ROUTES`. Never falls back to a direct
    provider — the failure mode this migration removes."""
    from krepis.router import resolve_group_spec

    try:
        spec, route = resolve_group_spec(ROUTER_GROUP, max_tokens=1024)
    except Exception as exc:
        raise RouterUnresolvable(
            f"router group {ROUTER_GROUP!r} did not resolve: {exc}"
        ) from exc
    resolved_route = route.get("route") if isinstance(route, dict) else None
    if resolved_route not in _COMPELLED_ROUTES:
        raise RouterUnresolvable(
            f"router group {ROUTER_GROUP!r} resolved to route {resolved_route!r} "
            f"(provider={getattr(spec, 'provider', None)!r}), which is not a "
            f"compelled path — refusing a direct-provider call chosen by "
            f"krepis's own fallback (model-router-policy.md §5). Compelled "
            f"routes: {sorted(_COMPELLED_ROUTES)}"
        )
    return spec


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

    def __init__(self, extracted, redaction) -> None:
        self.extracted = extracted
        self.redaction = redaction

    @property
    def ssn(self) -> str | None:
        ssns = self.redaction.ssns
        return ssns[0] if ssns else None

    def to_w2(self):
        return self.extracted


def build_w2_request(
    source_text: str,
    *,
    pdf_bytes: bytes | None = None,
) -> tuple[dict[str, Any], Any]:
    """Build the outbound request (system + redacted user content), redacting
    first and asserting no SSN.

    ``source_text`` is the OCR/extracted page text (may contain an SSN on
    entry); it is redacted here. ``pdf_bytes`` is NOT yet supported — see the
    module docstring — and raises :class:`ExtractionUnavailable` naming the
    gap rather than silently dropping the attachment or hand-rolling an
    unrouted multimodal call.

    Returns ``({"system": ..., "user_content": ...}, redaction)`` — the dict
    shape both feeds :func:`extract_w2`'s ``client.structured()`` call and
    serves as the audit payload for :func:`outbound_payload_json`.
    """
    from telos.ingest.prompt_loader import load_prompt
    from telos.ingest.redaction import assert_no_ssn, redact

    if pdf_bytes is not None:
        raise ExtractionUnavailable(
            "W-2 extraction with a pdf_bytes (vision/document) attachment is "
            "not supported: krepis's router-edge transport has no documented "
            "multimodal content-block contract and LLM_MODEL_REGISTRY.yaml "
            "declares no 'vision' capability tag to route on. Pass OCR'd "
            "source_text only. Tracked: telos-ops-I<N>."
        )

    redaction = redact(source_text)
    assert_no_ssn(redaction.text)

    request = {
        "system": load_prompt("w2_extraction"),
        "user_content": redaction.text,
    }
    return request, redaction


def extract_w2(
    source_text: str,
    *,
    client: Any | None = None,
    spec: Any | None = None,
    pdf_bytes: bytes | None = None,
) -> W2ExtractionResult:
    """Redact → call the model (krepis router edge, structured output) →
    validate → cross-foot.

    The SSN never reaches the API: it is redacted out and re-joined locally
    onto the returned :class:`W2ExtractionResult`. Cross-foot failure raises.

    ``client`` is a krepis-``LLMClient``-shaped test seam (exposes
    ``.structured(...)`` returning an object with ``.data``) — mirrors
    ``metron_ext.advisor.llm`` and ``vires``'s coach agent. ``spec`` lets a
    test pin a ``ModelSpec`` without faking the router. Production callers
    pass neither and the router resolves everything.
    """
    from krepis.llm import LLMClient, LLMError
    from krepis.llm_config import LLMConfigError

    from telos.ingest.schema import ExtractedW2, cross_foot_w2

    request, redaction = build_w2_request(source_text, pdf_bytes=pdf_bytes)

    if client is None:
        try:
            spec_cfg = spec if spec is not None else _resolve_spec()
        except (LLMConfigError, RouterUnresolvable) as e:
            raise ExtractionUnavailable(f"W-2 extraction router config error: {e}") from e
        client = LLMClient(spec_cfg, callsite_id=CALLSITE_ID)

    try:
        result = client.structured(
            system=request["system"],
            user_content=request["user_content"],
            schema=_W2_SCHEMA,
            schema_name=_SCHEMA_NAME,
            attempts=2,
            max_tokens=1024,
        )
    except LLMConfigError as e:
        raise ExtractionUnavailable(f"W-2 extraction config error: {e}") from e
    except LLMError as e:
        raise ExtractionUnavailable(
            f"model did not return a usable W-2 extraction: {e}"
        ) from e

    extracted = ExtractedW2(**_decimal_fields(result.data))
    cross_foot_w2(extracted)  # raises CrossFootError on mismatch
    return W2ExtractionResult(extracted=extracted, redaction=redaction)


def outbound_payload_json(request: dict[str, Any]) -> str:
    """Serialize an outbound request for auditing (used by the no-SSN test)."""
    return json.dumps(request, default=str)
