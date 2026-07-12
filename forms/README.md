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

## The one unsolved piece: the verified field map

IRS 1040-family AcroForms have **opaque positional field names**
(`topmostSubform[0].Page1[0].f1_11[0]`) and **no `/TU` tooltips** (verified:
`f1040.pdf` = 229 fields, 0 tooltips). So *which field is which 1040 line cannot
be read from the PDF*. A read-back test proves a value **lands** in a named
field; it never proves the field is the **semantically correct box**. A
mis-mapped dollar amount is a silent, high-stakes defect on a document mailed to
the IRS.

Therefore every profile ships `verified: false` with an **empty `field_map`**,
and `require_verified()` refuses filing-grade use until the map is confirmed. The
machinery is fully validated (synthetic AcroForm fixture + a mechanical
round-trip on the real `f1040.pdf`); only the map values are outstanding.

### DECISION NEEDED (telos-ops#10) — how to establish the verified map

The issue pre-commits to the AcroForm approach ("pypdf field mapping per form"),
so the remaining fork is *how the map is produced and verified*:

- **Option A — hand-authored map, human-confirmed once (recommended).** Run
  `describe_fields(template)` to get every field with its nearest printed label,
  hand-author `field_map` from that, and visually confirm each entry against the
  rendered form once. Durable thereafter; this is what commercial tax software
  does. `introspect.py` already does ~90% of the legwork.
- **Option B — geometric label-proximity auto-mapper.** Promote the
  `nearest_text` heuristic into a validated subsystem that assigns fields to line
  labels by coordinates. Removes the hand step but is itself a design-bearing
  component whose correctness must be validated (multi-column layout, checkboxes,
  continuation lines, ~7 forms).

Populating `field_map` (either way) is a **data-only** change to the YAML — no
code rework — because the map is a pure profile artifact.

## Adding a form

1. Commit the blank template to `forms/templates/<id>.pdf`.
2. `python -c "from telos.forms import describe_fields, paths; \
   [print(i.name, '|', i.field_type, '|', i.nearest_text) \
   for i in describe_fields(paths.template_path('<id>.pdf'))]"`
3. Author `src/telos/forms/profiles/<id>.yaml` `field_map`, confirm against the
   rendered form, flip `verified: true`.
