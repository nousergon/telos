import { moneyWhole, signClass } from "@/lib/format";
import type { IncomeSourceDetail } from "@/lib/types";
import { Section, Table } from "@/components/ui";

export function IncomeSourcesPanel({
  sources,
  ccy = "USD",
}: {
  sources: IncomeSourceDetail | null | undefined;
  ccy?: string;
}) {
  if (!sources) {
    return null;
  }

  const total = Number(sources.total);
  const wages = Number(sources.wages);
  const interest = Number(sources.interest);
  const dividends = Number(sources.ordinary_dividends);
  const capGain = Number(sources.net_capital_gain);
  const scheE = Number(sources.schedule_e_total);
  const other = Number(sources.other_income_total);

  // Show properties with non-zero income
  const properties = (sources.schedule_e_properties ?? []).filter(
    (p) => Number(p.net_income) !== 0,
  );

  return (
    <Section title="Income sources" note="estimated AGI components from the projection scenario">
      <Table head={["Source", "Estimated value"]}>
        <Row label="Wages (W-2)" value={wages} ccy={ccy} />
        <Row label="Taxable interest" value={interest} ccy={ccy} />
        <Row
          label="Ordinary dividends"
          value={dividends}
          ccy={ccy}
          hint={sources.qualified_dividends !== "0" ? `(${moneyWhole(Number(sources.qualified_dividends), ccy)} qualified)` : undefined}
        />
        <Row label="Net capital gain" value={capGain} ccy={ccy} />
        <Row label="Schedule E (rental)" value={scheE} ccy={ccy}>
          {properties.length > 0 && (
            <div className="mt-1 space-y-0.5 pl-4">
              {properties.map((p) => (
                <div key={p.arrangement_id} className="flex justify-between text-xs text-muted">
                  <span>{p.property_name}</span>
                  <span className={signClass(Number(p.net_income))}>
                    {moneyWhole(Number(p.net_income), ccy)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Row>
        {other !== 0 && <Row label="Other income" value={other} ccy={ccy} />}
        <tr className="border-t-2 border-line">
          <td className="px-4 py-2 text-xs font-semibold uppercase tracking-wide">
            Total income (AGI)
          </td>
          <td className="px-4 py-2 text-right text-lg font-semibold tabular-nums">
            {moneyWhole(total, ccy)}
          </td>
        </tr>
      </Table>

      {properties.length > 0 && (
        <div className="mt-3 space-y-1">
          <p className="text-xs font-medium uppercase tracking-wide text-muted">Rental properties</p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {properties.map((p) => (
              <div
                key={p.arrangement_id}
                className="rounded-md border border-line px-3 py-2 text-sm"
              >
                <div className="flex items-baseline justify-between">
                  <span className="font-medium">{p.property_name}</span>
                  <span className={`tabular-nums ${signClass(Number(p.net_income))}`}>
                    {moneyWhole(Number(p.net_income), ccy)}
                  </span>
                </div>
                {Number(p.depreciation_taken) !== 0 && (
                  <div className="flex justify-between text-xs text-muted">
                    <span>Depreciation</span>
                    <span className="tabular-nums">{moneyWhole(Number(p.depreciation_taken), ccy)}</span>
                  </div>
                )}
                {Number(p.suspended_loss) !== 0 && (
                  <div className="flex justify-between text-xs text-muted">
                    <span>Suspended loss c/f</span>
                    <span className="tabular-nums text-negative">{moneyWhole(Number(p.suspended_loss), ccy)}</span>
                  </div>
                )}
                <div className="mt-1 inline-block rounded-full bg-surface px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted">
                  {p.regime === "section_280a" ? "§280A" : p.regime === "section_469_passive" ? "§469 passive" : p.regime}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Section>
  );
}

function Row({
  label,
  value,
  ccy,
  hint,
  children,
}: {
  label: string;
  value: number;
  ccy: string;
  hint?: string;
  children?: React.ReactNode;
}) {
  return (
    <tr className="border-b border-line last:border-0">
      <td className="px-4 py-2">
        <span className="text-sm">{label}</span>
        {hint && <span className="ml-2 text-xs text-muted">{hint}</span>}
        {children}
      </td>
      <td className={`px-4 py-2 text-right tabular-nums text-sm ${value < 0 ? "text-negative" : ""}`}>
        {moneyWhole(value, ccy)}
      </td>
    </tr>
  );
}
