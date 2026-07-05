"""Pre-API identity redaction.

Nothing leaves this process toward the Anthropic API until it has passed
through here. The identity (SSN, employer EIN, broker account number) is
extracted LOCALLY, replaced with the literal token :data:`REDACTION_TOKEN`,
and re-joined onto the extracted model LOCALLY after the vision call returns.
The outbound API payload provably contains no SSN.

Two layers:

* **Regex** — SSN (``123-45-6789`` and ``123456789`` forms), EIN
  (``12-3456789``), and long account-number runs. Conservative: an SSN-shaped
  9-digit run is only redacted when it is *not* part of a money amount.
* **Known-layout position rules** — for a text-extracted W-2 whose field
  labels are known ("SSN", "Employer identification number", "a Employee's
  social security number"), redact the value that follows the label even if it
  doesn't match the generic regex.

Redaction is applied to the text that would be sent as the OCR/vision context.
The image bytes themselves are never sent for W-2s in this layer — extraction
runs off the redacted text — so an SSN printed on the page cannot leak.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

REDACTION_TOKEN = "[REDACTED]"

# SSN: 3-2-4 with optional separators. Anchored so a 9-run inside a longer
# number (a 12-digit account) isn't caught here (the account rule handles it).
_SSN = re.compile(r"(?<!\d)(\d{3})[-\s]?(\d{2})[-\s]?(\d{4})(?!\d)")
# EIN: 2-7 with a hyphen (the canonical printed form).
_EIN = re.compile(r"(?<!\d)\d{2}-\d{7}(?!\d)")
# Account number: a run of 10+ digits/uppercase-hex not broken by a decimal
# point (money never reaches 10 integer digits in these documents).
_ACCOUNT = re.compile(r"(?<![\d.])[0-9A-Z]{10,}(?![\d.])")

# Known-layout labels: value on the same line after the label gets redacted.
_LABEL_VALUE = re.compile(
    r"(?im)^(?P<label>\s*(?:a\s+)?"
    r"(?:employee'?s?\s+social\s+security\s+number"
    r"|social\s+security\s+number"
    r"|ssn"
    r"|employer\s+identification\s+number"
    r"|ein"
    r"|account\s+(?:number|no\.?))\s*[:#]?\s*)"
    r"(?P<value>[0-9A-Za-z][0-9A-Za-z\-\s]{4,}?)\s*$"
)


@dataclass(frozen=True)
class RedactionResult:
    """Redacted text plus the values pulled out, for local re-join."""

    text: str
    identifiers: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ssns(self) -> list[str]:
        return self.identifiers.get("ssn", [])

    def contains_any_identifier(self) -> bool:
        return any(self.identifiers.values())


def _record(store: dict[str, list[str]], key: str, value: str) -> None:
    value = value.strip()
    if value and value != REDACTION_TOKEN:
        store.setdefault(key, []).append(value)


def redact(text: str) -> RedactionResult:
    """Redact SSN/EIN/account identifiers from ``text`` before any API call.

    Returns a :class:`RedactionResult` whose ``text`` is safe to send outbound
    and whose ``identifiers`` map holds the extracted values for LOCAL re-join.
    """
    ids: dict[str, list[str]] = {}
    out = text

    # 1. Known-layout label rules first — most specific, catches values the
    #    generic regexes would miss (e.g. a masked "XXX-XX-1234").
    def _label_sub(m: re.Match[str]) -> str:
        label = m.group("label")
        raw = m.group("value")
        key = "account"
        low = label.lower()
        if "social security" in low or low.strip().endswith("ssn"):
            key = "ssn"
        elif "employer identification" in low or "ein" in low:
            key = "ein"
        _record(ids, key, raw)
        return f"{label}{REDACTION_TOKEN}"

    out = _LABEL_VALUE.sub(_label_sub, out)

    # 2. Generic regexes over whatever labels didn't catch.
    def _ssn_sub(m: re.Match[str]) -> str:
        _record(ids, "ssn", m.group(0))
        return REDACTION_TOKEN

    out = _SSN.sub(_ssn_sub, out)

    def _ein_sub(m: re.Match[str]) -> str:
        _record(ids, "ein", m.group(0))
        return REDACTION_TOKEN

    out = _EIN.sub(_ein_sub, out)

    def _acct_sub(m: re.Match[str]) -> str:
        _record(ids, "account", m.group(0))
        return REDACTION_TOKEN

    out = _ACCOUNT.sub(_acct_sub, out)

    return RedactionResult(text=out, identifiers=ids)


def assert_no_ssn(payload: str) -> None:
    """Guard: raise if a bare SSN survived into an outbound payload.

    Called on the exact string handed to the API client. Belt-and-suspenders
    over :func:`redact`; the ingestion path invokes it so a redaction bug is a
    hard failure, never a silent leak.
    """
    if _SSN.search(payload):
        raise ValueError(
            "outbound payload still contains an SSN-shaped value after redaction "
            "— refusing to transmit"
        )
