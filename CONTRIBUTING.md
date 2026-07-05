# Contributing to Telos

Thank you for your interest. Before any contribution can be accepted, please
read the two policies below — they are required and exist to keep the
project's licensing options intact.

## 1. Developer Certificate of Origin (DCO)

All commits must be signed off (`git commit -s`), certifying the
[Developer Certificate of Origin 1.1](https://developercertificate.org/).
Pull requests containing commits without a `Signed-off-by:` line will not be
merged.

## 2. Inbound license

By submitting a contribution, you agree that your contribution is licensed to
the project under the **MIT License**, regardless of the project's outbound
license (AGPL-3.0-only; see LICENSE). This permits the project to distribute
your contribution under its current license and under commercial licenses. If
you cannot contribute under these terms, please open an issue instead of a
pull request.

## Ground rules specific to a tax engine

- **Never commit tax documents, filled returns, or any personal data** — not
  even as test fixtures. Committed fixtures are synthetic or IRS-published
  (ATS scenarios) only; personal replay fixtures live outside the repository
  entirely (see README, "Local-first").
- **Every tax parameter needs a primary-source citation** (Revenue Procedure /
  form instruction) in `params/`. PRs adding uncited constants will not merge.
- **No LLM calls in `engine/`.** The arithmetic path is deterministic code only.
- **Version tags and `pyproject.toml` must move together.** Any PR that pushes
  a new `vX.Y.Z` tag must bump `[project].version` in `pyproject.toml` to
  `X.Y.Z` in the same PR (and vice versa) — don't let one drift ahead of the
  other.

## Scope

Issues and discussions are welcome. Substantial changes should start as an
issue before any code is written.
