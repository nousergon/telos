# Contributing to Telos

Thanks for your interest. Telos is licensed under **AGPL-3.0-only**.

## Developer Certificate of Origin (DCO)

All contributions are accepted under the [Developer Certificate of Origin
1.1](https://developercertificate.org/). By signing off your commits you
certify that you wrote the patch or otherwise have the right to submit it
under the project's license.

Sign off every commit with the `-s` flag:

```bash
git commit -s -m "your message"
```

This appends a `Signed-off-by: Your Name <you@example.com>` trailer. Commits
without a sign-off will not be merged.

## Inbound = outbound

Contributions are made under the same license as the project (AGPL-3.0-only).

## Ground rules specific to a tax engine

- **Never commit tax documents, filled returns, or any personal data** — not
  even as test fixtures. Test fixtures are synthetic or IRS-published (ATS
  scenarios).
- **Every tax parameter needs a primary-source citation** (Revenue Procedure /
  form instruction) in `params/`. PRs adding uncited constants will not merge.
- **No LLM calls in `engine/`.** The arithmetic path is deterministic code only.

## Development

See `README.md` for layout. Run the test suite and linter before opening a PR;
CI must be green.
