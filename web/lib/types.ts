// Types mirroring nousergon/telos contracts/tax_projection.schema.json (v1.x).

export type TaxProjectionQuarter = {
  quarter: number;
  due_date: string;
  required: string;
  paid: string;
  shortfall: string;
  status: "paid" | "overdue" | "upcoming";
};

export type TaxProjection = {
  schema_version: string;
  tax_year: number;
  as_of: string;
  filing_status: string;
  pack_status: string;
  projected: {
    agi: string;
    taxable_income: string;
    total_tax: string;
    total_withholding: string;
    estimated_payments_made: string;
    balance_due: string;
    effective_rate_on_agi: string;
    marginal_ordinary_rate: string;
  };
  safe_harbor: {
    basis: string;
    required_annual_payment: string;
    total_estimated_tax_due: string;
  };
  quarters: TaxProjectionQuarter[];
  headline: {
    payment_recommended: boolean;
    recommended_amount: string;
    next_due_date: string | null;
    message: string;
  };
};

export type TaxPlanningState = {
  stale: boolean;
  schema_error: string | null;
  projection: TaxProjection | null;
};

export type MetronTaxSummary = {
  available: boolean;
  reason: string | null;
  base_currency: string;
  as_of: string;
  realized_st_ytd: number;
  realized_lt_ytd: number;
  unrealized_total: number | null;
  unrealized_st: number | null;
  unrealized_lt: number | null;
  harvestable_loss: number | null;
};
