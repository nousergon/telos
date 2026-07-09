import { NextRequest, NextResponse } from "next/server";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import os from "node:os";

/**
 * Manual income / deduction overrides stored as a small JSON file
 * alongside the tax-projection artifact. The dashboard reads both and
 * shows the adjusted (what-if) picture.
 *
 * File format — a flat map of component field paths to override values:
 *   { "wages": 180000, "schedule_e_total": 40000 }
 * Fields absent from the map use their base (artifact) value.
 *
 * Resolved by TELOS_WORK_DIR env, then TAX_PROJECTION_PATH dir,
 * then ~/.telos/.
 * ------------------------------------------------------------------ */

type OverrideMap = Record<string, number | null>;

const FILE_NAME = "dashboard_adjustments.json";

async function resolvePath(): Promise<string> {
  const twd = process.env.TELOS_WORK_DIR?.trim();
  if (twd) {
    const dir = path.resolve(twd, "planning");
    await mkdir(dir, { recursive: true });
    return path.join(dir, FILE_NAME);
  }
  const tpPath = process.env.TAX_PROJECTION_PATH?.trim();
  if (tpPath) {
    const dir = path.dirname(path.resolve(tpPath));
    return path.join(dir, FILE_NAME);
  }
  const home = os.homedir();
  const dir = path.join(home, ".telos");
  await mkdir(dir, { recursive: true });
  return path.join(dir, FILE_NAME);
}

async function loadRaw(): Promise<OverrideMap> {
  const fp = await resolvePath();
  try {
    const raw = await readFile(fp, "utf8");
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    // Coerce any JSON number back to number, drop non-numeric entries
    const out: OverrideMap = {};
    for (const [k, v] of Object.entries(parsed)) {
      if (v === null || typeof v === "number") {
        out[k] = v as number | null;
      }
    }
    return out;
  } catch {
    return {};
  }
}

export type AdjustmentResponse = {
  ok: boolean;
  overrides: OverrideMap;
  path: string;
  error?: string;
};

/** GET /api/adjustments — return current override map. */
export async function GET(): Promise<NextResponse<AdjustmentResponse>> {
  const overrides = await loadRaw();
  const fp = await resolvePath();
  return NextResponse.json({ ok: true, overrides, path: fp });
}

/** PUT /api/adjustments — replace the entire override map. */
export async function PUT(request: NextRequest): Promise<NextResponse<AdjustmentResponse>> {
  try {
    const body = (await request.json()) as Record<string, unknown>;
    // Validate: values must be null or finite numbers
    const overrides: OverrideMap = {};
    for (const [k, v] of Object.entries(body)) {
      if (v === null) {
        overrides[k] = null;
      } else if (typeof v === "number" && Number.isFinite(v)) {
        overrides[k] = v;
      }
      // Silently skip non-compliant entries
    }

    const fp = await resolvePath();
    await mkdir(path.dirname(fp), { recursive: true });
    await writeFile(fp, JSON.stringify(overrides, null, 2) + "\n", "utf8");

    return NextResponse.json({
      ok: true,
      overrides,
      path: fp,
    });
  } catch (e) {
    return NextResponse.json(
      {
        ok: false,
        overrides: {},
        path: "",
        error: e instanceof Error ? e.message : "Failed to save adjustments",
      },
      { status: 500 },
    );
  }
}
