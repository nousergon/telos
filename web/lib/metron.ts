import "server-only";

import type { MetronTaxSummary } from "@/lib/types";

const API_URL = process.env.METRON_API_URL ?? "http://localhost:8000";

async function metronGet<T>(tenantId: string, path: string): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, {
    headers: { "X-Tenant-Id": tenantId },
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new Error(`Metron API ${path} returned ${resp.status}`);
  }
  return resp.json() as Promise<T>;
};

type MetronSummary = {
  base_currency: string;
};

type MetronIncomeYear = {
  year: number;
  realized_st: number;
  realized_lt: number;
};

type MetronTax = {
  as_of: string;
  unrealized_total: number | null;
  unrealized_position_total: number | null;
  unrealized_st: number | null;
  unrealized_lt: number | null;
  harvestable_loss: number | null;
};

/** Investment gains from Metron — downstream read-only consumer (M0 slot boundary). */
export async function loadMetronInvestmentGains(): Promise<MetronTaxSummary> {
  const tenantId = process.env.METRON_TENANT_ID?.trim();
  const portfolioId = process.env.METRON_PORTFOLIO_ID?.trim();
  if (!tenantId || !portfolioId) {
    return {
      available: false,
      reason: "Set METRON_TENANT_ID and METRON_PORTFOLIO_ID to show investment gains from Metron.",
      base_currency: "USD",
      as_of: "",
      realized_st_ytd: 0,
      realized_lt_ytd: 0,
      unrealized_total: null,
      unrealized_st: null,
      unrealized_lt: null,
      harvestable_loss: null,
    };
  }

  try {
    const taxable = "?taxable_only=true";
    const currentYear = new Date().getFullYear();
    const [summary, tax, income] = await Promise.all([
      metronGet<MetronSummary>(tenantId, `/portfolios/${portfolioId}/summary`),
      metronGet<MetronTax>(tenantId, `/portfolios/${portfolioId}/tax${taxable}`),
      metronGet<MetronIncomeYear[]>(tenantId, `/portfolios/${portfolioId}/income${taxable}`),
    ]);
    const ytd = income.find((y) => y.year === currentYear);
    const unrealized = tax.unrealized_position_total ?? tax.unrealized_total;
    return {
      available: true,
      reason: null,
      base_currency: summary.base_currency,
      as_of: tax.as_of,
      realized_st_ytd: ytd?.realized_st ?? 0,
      realized_lt_ytd: ytd?.realized_lt ?? 0,
      unrealized_total: unrealized,
      unrealized_st: tax.unrealized_st,
      unrealized_lt: tax.unrealized_lt,
      harvestable_loss: tax.harvestable_loss,
    };
  } catch (e) {
    return {
      available: false,
      reason: e instanceof Error ? e.message : "Could not load Metron investment gains.",
      base_currency: "USD",
      as_of: "",
      realized_st_ytd: 0,
      realized_lt_ytd: 0,
      unrealized_total: null,
      unrealized_st: null,
      unrealized_lt: null,
      harvestable_loss: null,
    };
  }
}
