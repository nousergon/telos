# Telos

> τέλος — *completion, purpose* — and the ancient Greek word for a tax.
> The customs house was a *teloneion*; the New Testament's tax collectors are *telōnai*.
> The tool that completes the year.

[![CI](https://github.com/nousergon/telos/actions/workflows/ci.yml/badge.svg)](https://github.com/nousergon/telos/actions/workflows/ci.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Status: Pre-Alpha](https://img.shields.io/badge/status-pre--alpha-orange.svg)](#status)

**A deterministic personal tax engine.** LLM document ingestion in front, pure-code
computation in the middle, official-form PDF output at the back — and every computed
line traceable to its inputs and its primary-source citation.

## Why

Commercial tax software shows you a number. Telos shows you the derivation:

```text
1040:line16 = 25000  [QDCGT worksheet; Rev. Proc. citation]
  taxable_income = 100000
    1040:line1a = 80000
      w2:acme.wages = 50000  [doc:w2-acme]
      w2:block.wages = 30000  [doc:w2-block]
    ...
```

## Load-bearing invariants

1. **No LLM in the arithmetic path — ever.** Models read documents and explain
   results; every computed number is deterministic, unit-tested code.
2. **Constants are data, sourced from primary documents.** Per-tax-year parameter
   packs (`params/tyNNNN.yaml`) where **every value carries a `source:` citation**
   (Revenue Procedure / form instruction) — enforced by the loader, not by
   convention. A `final` pack refuses to load with an unverified citation.
3. **Coverage guard — fail loud.** The engine declares its supported universe of
   document types and fields. An unrecognized field carrying a non-zero value is a
   hard, named failure — never a silently smaller return.
4. **Every output line is traceable.** `Traced` values carry provenance (source
   documents, parameter citations, worksheet paths) through every derivation.
5. **Local-first.** Personal tax data lives in `TELOS_DATA_DIR`, never in version
   control — not in this repo, not in any repo. CI runs synthetic and
   IRS-published fixtures only.

## What's here today (v0.1 — the foundation)

- `telos.engine.brackets` — progressive bracket arithmetic (tables come from
  parameter packs, never code), with property-tested invariants: monotonicity,
  boundary continuity, marginal-rate bounds.
- `telos.engine.trace` — the audit-trail primitive (`Traced`, `traced_sum`,
  provenance trees, `explain()`).
- `telos.engine.guard` — the coverage guard (`CoverageGuard`,
  `UnsupportedDocumentError`, `UnsupportedFieldError`).
- `telos.engine.rounding` — IRS whole-dollar rounding (`ROUND_HALF_UP`, not
  banker's rounding).
- `telos.params` — the parameter-pack loader with structural citation
  enforcement and `example / provisional / final` status gating.
- `telos.models` — typed source-document inputs (`W2`, `Form1099Int`,
  `Form1099Div`) with `extra="forbid"` and cross-field checks.

Deliberately **not** here yet: real tax-year constants. Authoring `ty2025.yaml` /
`ty2026.yaml` from primary sources (Revenue Procedures + final form instructions,
post-OBBBA) is tracked work — values are never transcribed from memory, an LLM's
or anyone's.

## Quickstart

```bash
git clone https://github.com/nousergon/telos.git
cd telos
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest          # 88 tests, coverage gate 90%
ruff check .
```

```python
from decimal import Decimal
from telos.engine import tax_from_brackets, round_whole_dollar
from telos.params import load_pack

pack = load_pack("params/example_pack.yaml")   # synthetic pack; real packs are tracked work
schedule = pack.brackets("ordinary_brackets.single")
print(round_whole_dollar(tax_from_brackets(Decimal(30_000), schedule)))  # 5000
sd = pack.get("standard_deduction.single")
print(sd.explain())   # value + its citation
```

## What it is not

- **Not tax advice.** Telos performs the arithmetic published in IRS forms and
  instructions, with citations. It does not recommend positions.
- **Not an e-file provider.** Output is a computed, explainable return for
  print-and-mail or for verification against commercial filing software.
- **No accuracy guarantee.** See `NOTICE`. You are responsible for your return.

## Status

Pre-alpha. Built for one real return first (the author's, TY2026); generality is
earned, not assumed. The next milestones: real parameter packs from primary
sources, the core 1040 assembly + Qualified Dividends & Capital Gain Tax
worksheet, and a replay harness that must reproduce a known-correct historical
return to the dollar before anything else is trusted.

## License

AGPL-3.0-only. See `LICENSE` and `NOTICE`. Contributions welcome under DCO +
MIT-inbound — see `CONTRIBUTING.md`.
