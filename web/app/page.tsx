import { InvestmentGainsPanel } from "@/components/investment-gains-panel";
import { TaxPlanningPanel } from "@/components/tax-planning-panel";
import { loadMetronInvestmentGains } from "@/lib/metron";
import { loadTaxPlanning } from "@/lib/tax-projection";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const [planning, gains] = await Promise.all([loadTaxPlanning(), loadMetronInvestmentGains()]);
  const ccy = gains.base_currency;

  return (
    <div>
      <h1 className="text-lg font-semibold">Tax dashboard</h1>
      <p className="text-sm text-muted">
        Year-round federal tax projection (telos) plus taxable investment gains (Metron). Personal operator surface —
        not part of the Metron beta/demo product.
      </p>

      <TaxPlanningPanel planning={planning} ccy={ccy} />
      <InvestmentGainsPanel gains={gains} />
    </div>
  );
}
