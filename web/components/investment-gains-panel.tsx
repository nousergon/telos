import Link from "next/link";

import { accountingMoney, accountingMoneyWhole, isoDate, moneyWhole, signClass } from "@/lib/format";
import type { MetronTaxSummary } from "@/lib/types";
import { Empty, Section, StatCard } from "@/components/ui";

export function InvestmentGainsPanel({ gains }: { gains: MetronTaxSummary }) {
  if (!gains.available) {
    return (
      <Section title="Investment gains" note="from Metron · taxable accounts">
        <Empty>{gains.reason ?? "Metron investment gains unavailable."}</Empty>
      </Section>
    );
  }

  const ccy = gains.base_currency;
  const currentYear = new Date().getFullYear();
  const priced = gains.unrealized_total != null;

  return (
    <Section
      title="Investment gains"
      note={`from Metron · taxable accounts · YTD ${currentYear}${gains.as_of ? ` · as of ${isoDate(gains.as_of)}` : ""}`}
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Realized ST (YTD)"
          value={accountingMoneyWhole(gains.realized_st_ytd, ccy)}
          valueClass={signClass(gains.realized_st_ytd)}
        />
        <StatCard
          label="Realized LT (YTD)"
          value={accountingMoneyWhole(gains.realized_lt_ytd, ccy)}
          valueClass={signClass(gains.realized_lt_ytd)}
        />
        <StatCard
          label="Unrealized total"
          value={priced ? accountingMoney(gains.unrealized_total as number, ccy) : "—"}
          valueClass={priced ? signClass(gains.unrealized_total as number) : ""}
          hint={priced ? "taxable positions" : "refresh prices in Metron"}
        />
        <StatCard
          label="Harvestable loss"
          value={gains.harvestable_loss != null ? moneyWhole(gains.harvestable_loss, ccy) : "—"}
          hint="available to harvest"
        />
      </div>
      {priced && gains.unrealized_st != null && gains.unrealized_lt != null ? (
        <p className="mt-2 text-xs text-muted">
          Lot-classified: ST {accountingMoneyWhole(gains.unrealized_st, ccy)}, LT{" "}
          {accountingMoneyWhole(gains.unrealized_lt, ccy)}.
        </p>
      ) : null}
      <p className="mt-2 text-xs text-muted">
        Read-only feed from{" "}
        <Link href="https://portfolio.nousergon.ai" className="text-accent hover:underline">
          Metron
        </Link>{" "}
        — per-lot detail stays on the Metron tax page. Telos consumes aggregates for the projection scenario.
      </p>
    </Section>
  );
}
