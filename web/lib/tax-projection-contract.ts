// The TaxProjection read model: validated against the shared contract, then
// graded for freshness. Pure (no fs, no "server-only") so `node --test` can
// exercise it directly; `tax-projection.ts` does the I/O.
//
// telos-ops#52 (audit PROD-04): the loader used to check only the
// schema_version major and then cast unknown JSON to `TaxProjection`, so
// `{"schema_version": "1.0"}` passed and crashed the panel, and a complete
// artifact from any date read as current — its payment recommendation was
// never freshness-gated.
//
// The shape is NOT restated here. `contracts/tax_projection.schema.json` (the
// producer's own pydantic export) is compiled as-is, with three mechanical
// tightenings derived from it rather than written beside it:
//   * `schema_version`'s `const` becomes "any 1.x" — the major gate below owns
//     version support, and a minor bump is additive by the contract's own text;
//   * a decimal field (`anyOf: [number, string]`) must hold a finite decimal
//     string when it holds a string, never "abc";
//   * a field the contract documents as an ISO date must be a real calendar
//     date (YYYY-MM-DD).
import Ajv, { type ErrorObject } from "ajv";

import type { TaxPlanningState, TaxProjection } from "./types";

export const SUPPORTED_SCHEMA_MAJOR = 1;

/**
 * Freshness budget for payment guidance. A projection is an operator-run
 * scenario, re-run at least once per estimated-payment quarter; 45 days covers
 * the longest gap between two §6654 installments (Jun 15 → Sep 15 is 92 days,
 * so a quarterly re-run lands mid-gap) with margin. Older than this, the panel
 * still shows the dated figures, but withholds "pay / don't pay" guidance.
 */
export const MAX_GUIDANCE_AGE_DAYS = 45;
/** Clock skew tolerated before an as_of counts as in the future. */
export const FUTURE_TOLERANCE_DAYS = 1;

const DECIMAL = "^-?\\d+(\\.\\d+)?$";
const ISO_DATE = "^\\d{4}-\\d{2}-\\d{2}$";
const DATE_FIELDS = new Set(["as_of", "due_date", "next_due_date"]);

type Json = Record<string, unknown>;

function tighten(node: unknown, key?: string): unknown {
  if (Array.isArray(node)) return node.map((n) => tighten(n));
  if (!node || typeof node !== "object") return node;
  const src = node as Json;
  const out: Json = {};
  for (const [k, v] of Object.entries(src)) {
    out[k] = k === "properties" && v && typeof v === "object"
      ? Object.fromEntries(Object.entries(v as Json).map(([pk, pv]) => [pk, tighten(pv, pk)]))
      : tighten(v);
  }
  const anyOf = out.anyOf as Json[] | undefined;
  if (Array.isArray(anyOf) && anyOf.some((b) => b.type === "number")) {
    out.anyOf = anyOf.map((b) => (b.type === "string" ? { ...b, pattern: DECIMAL } : b));
  }
  if (key && DATE_FIELDS.has(key)) {
    if (out.type === "string") out.pattern = ISO_DATE;
    if (Array.isArray(out.anyOf)) {
      out.anyOf = (out.anyOf as Json[]).map((b) =>
        b.type === "string" ? { ...b, pattern: ISO_DATE } : b,
      );
    }
  }
  if (key === "schema_version" && "const" in out) {
    delete out.const;
    delete out.default;
    out.pattern = `^${SUPPORTED_SCHEMA_MAJOR}\\.\\d+(\\.\\d+)?$`;
  }
  return out;
}

function realDate(iso: string): boolean {
  const d = new Date(`${iso}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === iso;
}

function describe(errors: ErrorObject[] | null | undefined): string {
  const first = (errors ?? [])[0];
  if (!first) return "unknown validation error";
  const where = first.instancePath || "(root)";
  return `${where} ${first.message ?? "is invalid"}`;
}

export type ContractValidator = (doc: unknown) => string | null;

/** Compile the shared contract into a validator returning an error or null. */
export function compileContract(schema: unknown): ContractValidator {
  // useDefaults fills the contract's own defaults (quarters: [], next_due_date: null)
  // on the parsed copy, so an artifact omitting them renders like the producer meant.
  const ajv = new Ajv({ allErrors: false, strict: false, useDefaults: true });
  const validate = ajv.compile(tighten(schema) as Json);
  return (doc: unknown) => {
    if (!validate(doc)) return describe(validate.errors);
    const p = doc as TaxProjection;
    const dates = [
      ["/as_of", p.as_of],
      ["/headline/next_due_date", p.headline.next_due_date],
      ...p.quarters.map((q, i) => [`/quarters/${i}/due_date`, q.due_date]),
    ] as const;
    for (const [where, value] of dates) {
      if (typeof value === "string" && !realDate(value)) return `${where} is not a calendar date`;
    }
    return null;
  };
}

function schemaVersionError(doc: Json): string | null {
  const version = String(doc.schema_version ?? "");
  const major = version.split(".", 1)[0];
  if (!/^\d+$/.test(major)) {
    return `tax_projection artifact has no parseable schema_version (${JSON.stringify(version)})`;
  }
  if (Number(major) !== SUPPORTED_SCHEMA_MAJOR) {
    return (
      `tax_projection schema_version ${version} is unsupported ` +
      `(this build reads major ${SUPPORTED_SCHEMA_MAJOR}.x) — update the dashboard ` +
      `or re-emit the artifact with a compatible telos version`
    );
  }
  return null;
}

const DAY_MS = 86_400_000;

/** Grade a parsed document: contract first, then freshness against `today`. */
export function gradeProjection(
  doc: unknown,
  validate: ContractValidator,
  today: Date,
): TaxPlanningState {
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) {
    return { stale: true, schema_error: null, projection: null, freshness: "unknown", age_days: null };
  }
  const versionError = schemaVersionError(doc as Json);
  const contractError = versionError ?? validate(doc);
  if (contractError) {
    return {
      stale: false,
      schema_error: versionError ?? `tax_projection artifact does not match its contract: ${contractError}`,
      projection: null,
      freshness: "unknown",
      age_days: null,
    };
  }
  const projection = doc as TaxProjection;
  const asOf = Date.parse(`${projection.as_of}T00:00:00Z`);
  const midnight = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  const age = Math.floor((midnight - asOf) / DAY_MS);
  // The last §6654 installment for tax year Y is due Jan 15 of Y+1.
  const yearClosed = midnight > Date.UTC(projection.tax_year + 1, 0, 15);
  const freshness =
    age < -FUTURE_TOLERANCE_DAYS
      ? "future"
      : age > MAX_GUIDANCE_AGE_DAYS
        ? "stale"
        : yearClosed
          ? "closed"
          : "current";
  return { stale: false, schema_error: null, projection, freshness, age_days: age };
}
