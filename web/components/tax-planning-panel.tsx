import {
  accountingMoney,
  accountingMoneyWhole,
  isoDate,
  moneyWhole,
  percent,
  signClass,
} from "@/lib/format";
import type { TaxPlanningState } from "@/lib/types";
import { Empty, Section, StatCard, Table } from "@/components/ui";

export function TaxPlanningPanel({ planning, ccy = "USD" }: { planning: TaxPlanningState; ccy?: string }) {
  if (planning.schema_error) {
    return (
      <Section title="Tax planning" note="year-round projection from the telos engine">
        <Empty>{planning.schema_error}</Empty>
      </Section>
    );
  }

  if (planning.stale || !planning.projection) {
    return (
      <Section title="Tax planning" note="year-round projection from the telos engine">
        <Empty>
          No tax projection yet — run <code>python -m telos.planning</code> against your income
          scenario and sync the artifact to the server.
        </Empty>
      </Section>
    );
  }

  const { projection } = planning;

  return (
    <Section
      title="Tax planning"
      note={`TY${projection.tax_year} projection · as of ${isoDate(projection.as_of)} · ${projection.pack_status} parameters`}
    >
      <div
        className={`mb-3 rounded-md border px-4 py-3 text-sm ${
          projection.headline.payment_recommended
            ? "border-negative/40 bg-negative/5"
            : "border-line bg-surface"
        }`}
      >
        <span className="font-medium">
          {projection.headline.payment_recommended
            ? `Estimated payment recommended: ${moneyWhole(Number(projection.headline.recommended_amount), ccy)}`
            : "No estimated payment needed right now"}
        </span>
        {projection.headline.next_due_date ? (
          <span className="text-muted"> · next due {isoDate(projection.headline.next_due_date)}</span>
        ) : null}
        <p className="mt-1 text-xs text-muted">{projection.headline.message}</p>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Projected total tax"
          value={moneyWhole(Number(projection.projected.total_tax), ccy)}
          hint={`on ${moneyWhole(Number(projection.projected.agi), ccy)} AGI`}
        />
        <StatCard
          label="Effective / marginal rate"
          value={`${percent(Number(projection.projected.effective_rate_on_agi))} / ${percent(Number(projection.projected.marginal_ordinary_rate))}`}
          hint="on AGI / ordinary bracket"
        />
        <StatCard
          label="Safe harbor required"
          value={moneyWhole(Number(projection.safe_harbor.required_annual_payment), ccy)}
          hint={projection.safe_harbor.basis.replaceAll("_", " ")}
        />
        <StatCard
          label="Balance due at filing"
          value={accountingMoneyWhole(Number(projection.projected.balance_due), ccy)}
          valueClass={signClass(-Number(projection.projected.balance_due))}
          hint="after withholding + payments"
        />
      </div>
      {projection.quarters.length > 0 ? (
        <div className="mt-3">
          <Table head={["Installment", "Due", "Required", "Paid", "Shortfall", "Status"]}>
            {projection.quarters.map((q) => (
              <tr key={q.quarter} className="border-b border-line last:border-0">
                <td className="px-4 py-2 font-medium">Q{q.quarter}</td>
                <td className="px-4 py-2 text-right text-muted">{isoDate(q.due_date)}</td>
                <td className="px-4 py-2 text-right tabular-nums">{moneyWhole(Number(q.required), ccy)}</td>
                <td className="px-4 py-2 text-right tabular-nums">{moneyWhole(Number(q.paid), ccy)}</td>
                <td
                  className={`px-4 py-2 text-right tabular-nums ${Number(q.shortfall) > 0 ? "text-negative" : ""}`}
                >
                  {Number(q.shortfall) > 0 ? moneyWhole(Number(q.shortfall), ccy) : "—"}
                </td>
                <td className="px-4 py-2 text-right">
                  <span
                    className={`text-xs uppercase tracking-wide ${
                      q.status === "overdue" ? "font-medium text-negative" : q.status === "paid" ? "text-muted" : ""
                    }`}
                  >
                    {q.status}
                  </span>
                </td>
              </tr>
            ))}
          </Table>
        </div>
      ) : (
        <p className="mt-2 text-xs text-muted">
          Withholding meets the required annual payment — no 1040-ES installments due.
        </p>
      )}
      <p className="mt-2 text-xs text-muted">
        Deterministic projection from the telos engine ({projection.filing_status.replaceAll("_", " ")}, withholding{" "}
        {moneyWhole(Number(projection.projected.total_withholding), ccy)}, estimated payments made{" "}
        {moneyWhole(Number(projection.projected.estimated_payments_made), ccy)}). §6654 safe-harbor math; statutory due
        dates. Descriptive, not advice.
      </p>
    </Section>
  );
}
