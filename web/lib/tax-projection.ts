import "server-only";

import { readFile } from "node:fs/promises";
import path from "node:path";

import { compileContract, gradeProjection, type ContractValidator } from "@/lib/tax-projection-contract";
import type { TaxPlanningState } from "@/lib/types";

const MISSING: TaxPlanningState = {
  stale: true,
  schema_error: null,
  projection: null,
  freshness: "unknown",
  age_days: null,
};

let validator: Promise<ContractValidator> | null = null;

/** The shared contract (`contracts/tax_projection.schema.json`), compiled once. */
function contract(): Promise<ContractValidator> {
  if (!validator) {
    const configured = process.env.TAX_PROJECTION_SCHEMA_PATH;
    const schemaPath = configured
      ? path.resolve(configured)
      : path.resolve(process.cwd(), "../contracts/tax_projection.schema.json");
    validator = readFile(schemaPath, "utf8").then((text) => compileContract(JSON.parse(text)));
    validator.catch(() => {
      validator = null; // retry on the next request rather than caching a failure
    });
  }
  return validator;
}

/**
 * Read the last-good TaxProjection artifact from disk (M0 contract — no telos
 * import), validate it against the shared contract and grade its freshness
 * (`tax-projection-contract.ts`). An unreadable contract fails closed: the
 * artifact is never shown unvalidated.
 */
export async function loadTaxPlanning(): Promise<TaxPlanningState> {
  const configured = process.env.TAX_PROJECTION_PATH;
  const artifactPath = configured
    ? path.resolve(configured)
    : path.resolve(process.cwd(), "../cache/tax_projection.json");

  let raw: string;
  try {
    raw = await readFile(artifactPath, "utf8");
  } catch {
    return MISSING;
  }

  let doc: unknown;
  try {
    doc = JSON.parse(raw);
  } catch {
    return MISSING;
  }

  let validate: ContractValidator;
  try {
    validate = await contract();
  } catch (exc) {
    return {
      ...MISSING,
      stale: false,
      schema_error: `tax_projection contract could not be loaded (${String(exc)}) — the artifact is not shown unvalidated`,
    };
  }
  return gradeProjection(doc, validate, new Date());
}
