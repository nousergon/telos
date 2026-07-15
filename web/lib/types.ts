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

// NOTE: not yet produced by the backend projection artifact — these types
// describe the shape consumed by the (currently unwired) income-sources,
// deduction, and what-if panels. See config#2551.

export type ScheduleEPropertyItem = {
  arrangement_id: string;
  property_name: string;
  net_income: string;
  depreciation_taken: string;
  suspended_loss: string;
  regime: string;
};

export type IncomeSourceDetail = {
  total: string;
  wages: string;
  interest: string;
  ordinary_dividends: string;
  qualified_dividends: string;
  net_capital_gain: string;
  schedule_e_total: string;
  other_income_total: string;
  schedule_e_properties?: ScheduleEPropertyItem[] | null;
};

export type AdjustmentItem = {
  name: string;
  amount: string;
};

export type AdjustmentsDetail = {
  total: string;
  items: AdjustmentItem[];
};

export type DeductionDetail = {
  type: "standard" | "itemized";
  standard_amount: string;
  itemized_total: string;
  qbi: string;
  medical: string;
  salt: string;
  mortgage_interest: string;
  charitable: string;
  other_itemized: string;
};
