import "server-only";

import { readFile } from "node:fs/promises";
import path from "node:path";

import type { TaxPlanningState, TaxProjection } from "@/lib/types";

const SUPPORTED_SCHEMA_MAJOR = 1;

function schemaError(projection: TaxProjection): string | null {
  const version = String(projection.schema_version ?? "");
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

/** Read the last-good TaxProjection artifact from disk (M0 contract — no telos import). */
export async function loadTaxPlanning(): Promise<TaxPlanningState> {
  const configured = process.env.TAX_PROJECTION_PATH;
  const artifactPath = configured
    ? path.resolve(configured)
    : path.resolve(process.cwd(), "../cache/tax_projection.json");

  let raw: string;
  try {
    raw = await readFile(artifactPath, "utf8");
  } catch {
    return { stale: true, schema_error: null, projection: null };
  }

  let doc: unknown;
  try {
    doc = JSON.parse(raw);
  } catch {
    return { stale: true, schema_error: null, projection: null };
  }

  if (!doc || typeof doc !== "object" || Array.isArray(doc)) {
    return { stale: true, schema_error: null, projection: null };
  }

  const projection = doc as TaxProjection;
  const err = schemaError(projection);
  if (err) {
    return { stale: false, schema_error: err, projection: null };
  }

  return { stale: false, schema_error: null, projection };
}
