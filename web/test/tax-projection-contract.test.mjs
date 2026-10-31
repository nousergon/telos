// Runtime consumer-contract tests for the TaxProjection read model
// (telos-ops#52). SYNTHETIC data only — never a real return.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  MAX_GUIDANCE_AGE_DAYS,
  compileContract,
  gradeProjection,
} from "../lib/tax-projection-contract.ts";

const schema = JSON.parse(
  readFileSync(new URL("../../contracts/tax_projection.schema.json", import.meta.url), "utf8"),
);
const validate = compileContract(schema);
const TODAY = new Date("2026-05-20T15:00:00Z");

function synthetic(overrides = {}) {
  return {
    schema_version: "1.1.0",
    tax_year: 2026,
    as_of: "2026-05-10",
    filing_status: "single",
    pack_status: "example",
    projected: {
      agi: "100000.00",
      taxable_income: "85000.00",
      total_tax: "14000.00",
      total_withholding: "9000.00",
      estimated_payments_made: "1000.00",
      balance_due: "4000.00",
      effective_rate_on_agi: "0.1400",
      marginal_ordinary_rate: "0.22",
    },
    safe_harbor: {
      basis: "100pct_prior_year",
      required_annual_payment: "12000.00",
      total_estimated_tax_due: "3000.00",
    },
    quarters: [
      { quarter: 2, due_date: "2026-06-15", required: "750.00", paid: "0", shortfall: "750.00", status: "upcoming" },
    ],
    headline: {
      payment_recommended: true,
      recommended_amount: "750.00",
      next_due_date: "2026-06-15",
      message: "synthetic",
    },
    ...overrides,
  };
}

const grade = (doc, today = TODAY) => gradeProjection(doc, validate, today);

test("a complete, timely synthetic artifact is current and keeps its figures", () => {
  const state = grade(synthetic());
  assert.equal(state.schema_error, null);
  assert.equal(state.freshness, "current");
  assert.equal(state.age_days, 10);
  assert.equal(state.projection.projected.total_tax, "14000.00");
  assert.equal(state.projection.headline.recommended_amount, "750.00");
});

test("the audit's probe: a bare schema_version never reaches rendering", () => {
  const state = grade({ schema_version: "1.0" });
  assert.equal(state.projection, null);
  assert.match(state.schema_error, /does not match its contract/);
});

test("a missing nested field is a contract error, not a crash", () => {
  const doc = synthetic();
  delete doc.headline.payment_recommended;
  const state = grade(doc);
  assert.equal(state.projection, null);
  assert.match(state.schema_error, /payment_recommended/);
});

test("an unsupported major is refused with the version named", () => {
  const state = grade(synthetic({ schema_version: "2.0.0" }));
  assert.equal(state.projection, null);
  assert.match(state.schema_error, /2\.0\.0 is unsupported/);
});

test("an older 1.x minor is still read", () => {
  assert.equal(grade(synthetic({ schema_version: "1.0.0" })).schema_error, null);
});

test("a non-decimal amount string is refused", () => {
  const doc = synthetic();
  doc.projected.total_tax = "lots";
  assert.match(grade(doc).schema_error, /total_tax/);
});

test("a non-calendar date is refused", () => {
  assert.match(grade(synthetic({ as_of: "2026-02-30" })).schema_error, /as_of/);
  assert.match(grade(synthetic({ as_of: "May 10" })).schema_error, /as_of/);
});

test("an unknown top-level field is refused (the contract forbids it)", () => {
  assert.match(grade(synthetic({ surprise: 1 })).schema_error, /must NOT have additional properties/);
});

test("contract defaults are filled: an artifact without quarters renders an empty table", () => {
  const doc = synthetic();
  delete doc.quarters;
  delete doc.headline.next_due_date;
  const state = grade(doc);
  assert.deepEqual(state.projection.quarters, []);
  assert.equal(state.projection.headline.next_due_date, null);
});

test("a projection older than the budget is stale: guidance is withheld", () => {
  const old = new Date(TODAY.getTime() + (MAX_GUIDANCE_AGE_DAYS + 1 - 10) * 86_400_000);
  const state = grade(synthetic(), old);
  assert.equal(state.freshness, "stale");
  assert.equal(state.age_days, MAX_GUIDANCE_AGE_DAYS + 1);
  assert.notEqual(state.projection, null); // dated figures still shown
});

test("a projection dated in the future is flagged, not current", () => {
  assert.equal(grade(synthetic({ as_of: "2026-06-01" })).freshness, "future");
});

test("a closed tax year gives no current guidance", () => {
  const state = grade(synthetic({ tax_year: 2025, as_of: "2026-05-10" }));
  assert.equal(state.freshness, "closed");
});

test("non-object JSON is a missing artifact, never a projection", () => {
  for (const doc of [null, [], "x", 3]) {
    const state = grade(doc);
    assert.equal(state.projection, null);
    assert.equal(state.stale, true);
  }
});
