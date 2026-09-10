## What & why

<!-- What does this change and why? Link any related issue. -->

## Checklist

- [ ] Tests added/updated for the behavior change
- [ ] `pytest` passes locally — the coverage floor in `pyproject.toml` is a ratchet, raised as coverage improves and never lowered to make a change pass
- [ ] `ruff check .` is clean for files I touched
- [ ] No secrets, real tax documents, or real PII committed (synthetic fixtures only)
- [ ] The coverage guard (`telos.engine.guard`) still declares every form/line item this change touches — no silent bypass

## Test plan

<!-- How you verified this works. -->

---

Prepared by: <model-name> via [Claude Code](https://claude.com/claude-code)
