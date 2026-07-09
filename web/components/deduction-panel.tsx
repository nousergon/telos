import { moneyWhole } from "@/lib/format";
import type { AdjustmentsDetail, DeductionDetail } from "@/lib/types";
import { Section } from "@/components/ui";

export function DeductionPanel({
  detail,
  adjustments,
  totalIncome,
  agi,
  ccy = "USD",
}: {
  detail: DeductionDetail | null | undefined;
  adjustments: AdjustmentsDetail | null | undefined;
  totalIncome?: number;
  agi?: number;
  ccy?: string;
}) {
  const adj = adjustments;
  const adjTotal = adj ? Number(adj.total) : 0;

  // Major solopreneur deduction categories to highlight
  const majorLabels = new Set([
    "sehi", "self-employed health insurance", "cobra health insurance", "sehi (cobra health insurance)",
    "se tax half", "self-employment tax half", "se tax half (employer-equivalent)",
    "solo 401(k)", "solo 401(k) contribution", "sep-ira", "retirement contribution",
    "hsa", "hsa contribution",
    "home office", "home office (simplified)", "home office deduction",
    "business expenses", "business expenses (software, supplies)",
  ]);

  return (
    <Section title="Deductions & adjustments" note="above-the-line + below-the-line">
      {/* AGI waterfall */}
      {((adj && adjTotal > 0) || (totalIncome !== undefined && totalIncome > 0)) && (
        <div className="mb-4 overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line bg-surface text-left text-xs uppercase tracking-wide text-muted">
                <th className="px-4 py-2 font-medium">Step</th>
                <th className="px-4 py-2 text-right font-medium">Amount</th>
              </tr>
            </thead>
            <tbody>
              {totalIncome !== undefined && (
                <tr className="border-b border-line">
                  <td className="px-4 py-2 text-sm">Total income (line 9)</td>
                  <td className="px-4 py-2 text-right tabular-nums">{moneyWhole(totalIncome, ccy)}</td>
                </tr>
              )}
              {adjTotal > 0 && (
                <tr className="border-b border-line bg-accent/5">
                  <td className="px-4 py-2">
                    <span className="text-sm font-medium text-accent">− Above-the-line adjustments</span>
                    <span className="ml-2 text-[10px] uppercase tracking-wide text-accent">solopreneur</span>
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums text-accent">({moneyWhole(adjTotal, ccy)})</td>
                </tr>
              )}
              {agi !== undefined && (
                <tr className={`border-b border-line ${adjTotal > 0 ? "font-medium" : ""}`}>
                  <td className="px-4 py-2 text-sm">= Adjusted gross income (line 11)</td>
                  <td className="px-4 py-2 text-right tabular-nums">{moneyWhole(agi, ccy)}</td>
                </tr>
              )}
              {detail && (
                <tr className="border-b border-line">
                  <td className="px-4 py-2 text-sm">− Deduction (line 12)</td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {moneyWhole(
                      detail.type === "itemized"
                        ? Number(detail.itemized_total)
                        : Number(detail.standard_amount),
                      ccy,
                    )}
                  </td>
                </tr>
              )}
              {detail && Number(detail.qbi) > 0 && (
                <tr className="border-b border-line">
                  <td className="px-4 py-2 text-sm">− QBI deduction</td>
                  <td className="px-4 py-2 text-right tabular-nums">({moneyWhole(Number(detail.qbi), ccy)})</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Above-the-line deductions detail */}
      {adj && adjTotal > 0 && adj.items.length > 0 && (
        <div className="mb-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
            Solopreneur deductions (Schedule 1 Part II)
          </h3>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {adj.items.map((item) => {
              const isMajor = majorLabels.has(item.name.toLowerCase().trim());
              return (
                <div
                  key={item.name}
                  className={`rounded-md border p-3 ${
                    isMajor
                      ? "border-accent/30 bg-accent/5"
                      : "border-line bg-surface"
                  }`}
                >
                  <div className="flex items-baseline justify-between">
                    <span className={`text-sm ${isMajor ? "font-medium" : ""}`}>
                      {item.name}
                      {isMajor && (
                        <span className="ml-1.5 rounded-full bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-accent">
                          major
                        </span>
                      )}
                    </span>
                    <span className="tabular-nums text-sm text-positive">
                      −{moneyWhole(Number(item.amount), ccy)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Standard vs Itemized (if detail exists) */}
      {detail && (() => {
        const std = Number(detail.standard_amount);
        const itemized = Number(detail.itemized_total);
        const isItemized = detail.type === "itemized";
        const advantage = Math.abs(itemized - std);

        return (
          <>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
              Below-the-line deduction
            </h3>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div
                className={`rounded-lg border p-4 ${
                  !isItemized
                    ? "border-positive/40 bg-positive/5"
                    : "border-line bg-surface"
                }`}
              >
                <div className="text-xs uppercase tracking-wide text-muted">Standard deduction</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums">
                  {moneyWhole(std, ccy)}
                </div>
                {!isItemized && (
                  <div className="mt-1 text-xs font-medium text-positive">✓ Chosen</div>
                )}
              </div>
              <div
                className={`rounded-lg border p-4 ${
                  isItemized
                    ? "border-positive/40 bg-positive/5"
                    : "border-line bg-surface"
                }`}
              >
                <div className="text-xs uppercase tracking-wide text-muted">Itemized deductions</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums">
                  {moneyWhole(itemized, ccy)}
                </div>
                {isItemized && (
                  <div className="mt-1 text-xs font-medium text-positive">✓ Chosen</div>
                )}
              </div>
            </div>

            {isItemized && (
              <div className="mt-3 overflow-x-auto rounded-lg border border-line">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-line bg-surface text-left text-xs uppercase tracking-wide text-muted">
                      <th className="px-4 py-2 font-medium">Component</th>
                      <th className="px-4 py-2 text-right font-medium">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Number(detail.medical) > 0 && (
                      <ItemizedRow label="Medical expenses" value={Number(detail.medical)} ccy={ccy} />
                    )}
                    {Number(detail.salt) > 0 && (
                      <ItemizedRow label="State & local taxes (SALT)" value={Number(detail.salt)} ccy={ccy} />
                    )}
                    {Number(detail.mortgage_interest) > 0 && (
                      <ItemizedRow label="Mortgage interest" value={Number(detail.mortgage_interest)} ccy={ccy} />
                    )}
                    {Number(detail.charitable) > 0 && (
                      <ItemizedRow label="Charitable gifts" value={Number(detail.charitable)} ccy={ccy} />
                    )}
                    {Number(detail.other_itemized) > 0 && (
                      <ItemizedRow label="Other itemized" value={Number(detail.other_itemized)} ccy={ccy} />
                    )}
                    <tr className="border-t-2 border-line">
                      <td className="px-4 py-2 text-xs font-semibold uppercase tracking-wide">Total itemized</td>
                      <td className="px-4 py-2 text-right text-base font-semibold tabular-nums">
                        {moneyWhole(itemized, ccy)}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}

            <p className="mt-2 text-xs text-muted">
              {isItemized
                ? `Itemizing beats the standard deduction by ${moneyWhole(advantage, ccy)}.`
                : `Standard deduction beats itemized by ${moneyWhole(advantage, ccy)}.`}
              {Number(detail.qbi) > 0 &&
                ` QBI deduction: ${moneyWhole(Number(detail.qbi), ccy)}.`}
            </p>
          </>
        );
      })()}
    </Section>
  );
}

function ItemizedRow({ label, value, ccy }: { label: string; value: number; ccy: string }) {
  return (
    <tr className="border-b border-line last:border-0">
      <td className="px-4 py-2">{label}</td>
      <td className="px-4 py-2 text-right tabular-nums">{moneyWhole(value, ccy)}</td>
    </tr>
  );
}
