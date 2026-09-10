# Security Policy

## Reporting a vulnerability

If you find a security vulnerability in Telos, please report it privately:

- **Preferred:** open a [GitHub Security Advisory](https://github.com/nousergon/telos/security/advisories/new). This keeps the discussion private until a fix ships.
- **Alternative:** email `security@nousergon.ai` with a description and reproduction steps.

Please **do not** open a public issue for security reports. I aim to acknowledge within 72 hours and ship a fix or mitigation within 14 days for high-severity issues.

## Scope

Telos is a personal, self-hosted tax engine: LLM document ingestion in front, pure-code
computation in the middle, official-form PDF output at the back. The sensitive surface is
**tax-document and PII handling**. In scope:

- **PII / document exposure:** any path that leaks a W-2, 1099, or other ingested tax
  document — or values extracted from one (SSNs, income, account numbers) — through logs,
  error messages, telemetry, or a generated artifact that escapes the operator's own
  `TELOS_DATA_DIR`.
- **Injection / escalation:** unsafe handling of LLM-extracted document content that
  reaches a shell, filesystem path, or the PDF form-filling layer (`src/telos/forms/`).
- **Determinism / correctness escapes:** any path where the coverage guard
  (`telos.engine.guard`) is silently bypassed, letting an unsupported form or line item
  compute a number without declaring it.
- **Supply-chain:** a dependency or install path that could execute untrusted code during
  `pip install -e .` or ingestion.

Out of scope:

- Issues requiring local filesystem/process access (if your machine is compromised, the
  threat model has already failed — `TELOS_DATA_DIR` and your API keys live there).
- Vulnerabilities in upstream dependencies not yet publicly disclosed — report those
  upstream first.

## Threat model assumptions

- **Single-user, local-first.** There is no multi-user model in this engine; tax data
  stays in the operator's own `TELOS_DATA_DIR`.
- **Credentials for the ingestion path route through the krepis router edge** — no
  direct provider API key lives in this repo's runtime config.
- **The model's ingestion output is treated as untrusted structured data**, validated by
  Pydantic schemas with `extra="forbid"` before it reaches any downstream computation.
- **HTTPS** is assumed for all router-edge traffic.

## Hardening recommendations for self-hosters

- Keep `TELOS_DATA_DIR` and any `.env` at `600` and never commit them.
- Never place real tax documents or fixtures containing real PII into the repo tree —
  synthetic fixtures only (`reportlab`-generated fakes in `tests/fixtures/`).
- Set provider-side spend limits on the ingestion path's key.
