# `forms/` — official IRS form output layer

The back of the telos pipeline: take the engine's computed line values and
transcribe them into the **official fillable IRS PDFs**, then assemble a
print-and-mail package.

- **Code:** `src/telos/forms/` (outside `src/telos/engine/` — pure output
  plumbing, imports nothing from the engine).
- **Blank templates:** `forms/templates/*.pdf` — public-domain US-gov works,
  committed (the only PDFs the repo tracks; `.gitignore` excepts them).
- **Filled output:** `TELOS_DATA_DIR` only — it embeds personal figures and
  never lands in a repo.

## Pieces

| Module | Role |
|---|---|
| `paths.py` | template lookup (in-tree) + filled-output resolution (TELOS_DATA_DIR only) |
| `profile.py` | `FormProfile` — `{engine line key → AcroForm field name}` map + `verified` gate |
| `filler.py` | fill an AcroForm (unknown-field guard, **XFA drop**, NeedAppearances) |
| `package.py` | concatenate filled forms in filing order |
| `introspect.py` | dump each field's name/type/rect/**nearest printed label** — the mapping aid |
| `profiles/*.yaml` | committed per-form profiles |

## The verified field map

IRS 1040-family AcroForms have **opaque positional field names**
(`topmostSubform[0].Page1[0].f1_11[0]`) and **no `/TU` tooltips** (verified:
`f1040.pdf` = 229 fields, 0 tooltips). So *which field is which 1040 line cannot
be read from the PDF*. A read-back test proves a value **lands** in a named
field; it never proves the field is the **semantically correct box**. A
mis-mapped dollar amount is a silent, high-stakes defect on a document mailed to
the IRS.

Every profile therefore ships `verified: false` with an **empty `field_map`**
until the map is established and confirmed against the rendered form;
`require_verified()` refuses filing-grade use before that.

### RESOLVED (telos-ops#10, Brian's 2026-07-13 Operator decision: Option A)

`f1040.yaml` is now hand-authored + verified: each mapped field's widget rect
was rendered against the actual printed page (200dpi overlay, both pages) and
confirmed by eye to sit in the stated line's box — `describe_fields()`'s
nearest-text heuristic was used only as a starting candidate list, never
trusted directly (it repeatedly latched onto unrelated header/OMB text for
several fields). Only engine-computed lines are mapped; real 1040 lines the
engine doesn't yet model are left unmapped rather than guessed. See the
`field_map` comments in `profiles/f1040.yaml` for the full per-field rationale.

**Option B (geometric label-proximity auto-mapper)** remains a possible future
upgrade if/when more forms are added — promoting `nearest_text` into a
validated subsystem would remove the hand step, but is itself a design-bearing
component (multi-column layout, checkboxes, continuation lines, ~7 forms) that
would need its own validation pass. Not needed for f1040.

Populating `field_map` for a new form is a **data-only** change to its YAML —
no code rework — because the map is a pure profile artifact.

## Adding a form

1. Commit the blank template to `forms/templates/<id>.pdf`.
2. `python -c "from telos.forms import describe_fields, paths; \
   [print(i.name, '|', i.field_type, '|', i.nearest_text) \
   for i in describe_fields(paths.template_path('<id>.pdf'))]"`
3. Author `src/telos/forms/profiles/<id>.yaml` `field_map`, confirm against the
   rendered form, flip `verified: true`.
