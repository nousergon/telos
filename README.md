# Telos

**A deterministic personal tax engine.** LLM document ingestion in front, pure-code
computation in the middle, official-form PDF output at the back.

*Telos* (τέλος): completion, purpose, end — and the ancient Greek word for a tax or
duty (the customs house was a *teloneion*; the New Testament's tax collectors are
*telōnai*). The tool that completes the year.

## What it is

Telos computes a U.S. federal individual income tax return (Form 1040 + supporting
schedules) from source documents, and shows its work:

- **`ingest/`** — LLM-assisted extraction of source documents (W-2, consolidated
  1099s, 1098) into typed, human-confirmed inputs. Extractions must cross-foot
  against each document's own summary totals.
- **`engine/`** — pure deterministic computation. Typed inputs → `Return` object.
  No I/O, no LLM, no clock. Every IRS worksheet is a named, unit-tested function.
- **`forms/`** — fills official IRS PDF forms (free AcroForms from irs.gov) and
  assembles a print-ready package.
- **`review/`** — explanation and audit-trail layer: every output line traces to
  its input values, worksheet path, and parameter citations.

## Load-bearing invariants

1. **No LLM in the arithmetic path — ever.** Models read documents and explain
   results; every computed number is deterministic code.
2. **Constants are data, sourced from primary documents.** Per-tax-year parameter
   packs (`params/tyNNNN.yaml`) where every value carries a `source:` citation
   (Revenue Procedure / form instruction). Never from model memory.
3. **Coverage guard — fail loud.** The engine declares its supported universe
   (document types, form boxes, form modules). Anything unrecognized is a hard
   failure with a named gap, never a silently smaller return.
4. **Replay gate.** A tax year's engine is trusted only after reproducing a
   known-correct historical return to the dollar.
5. **Local-first.** Tax documents and filled returns live outside the repository
   and never enter version control. The only network egress is LLM API calls at
   ingestion, with identifiers redacted before the call.

## What it is not

- **Not tax advice.** Telos performs the arithmetic published in IRS forms and
  instructions, with citations. It does not recommend positions.
- **Not an e-file provider.** Output is a computed, explainable return for
  print-and-mail or for verification against commercial filing software.
- **No accuracy guarantee.** See `NOTICE`. You are responsible for your return.

## Status

Pre-alpha, personal-use. Built for one real return first; generality is earned,
not assumed.

## License

AGPL-3.0-only. See `LICENSE` and `NOTICE`. Contributions under DCO — see
`CONTRIBUTING.md`.
