// Display formatting — mirrors metron/web/lib/format.ts (subset used by the dashboard).

export function moneyWhole(value: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

export function accountingMoneyWhole(value: number, currency = "USD"): string {
  const formatted = moneyWhole(Math.abs(value), currency);
  return value < 0 ? `(${formatted})` : formatted;
}

export function accountingMoney(value: number, currency = "USD"): string {
  const formatted = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(Math.abs(value));
  return value < 0 ? `(${formatted})` : formatted;
}

export function percent(ratio: number): string {
  const pct = ratio * 100;
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : "";
  return `${sign}${Math.abs(pct).toFixed(1)}%`;
}

export function isoDate(value: string): string {
  const [y, m, d] = value.split("-");
  if (!y || !m || !d) return value;
  const month = new Intl.DateTimeFormat("en-US", { month: "short", timeZone: "UTC" }).format(
    new Date(Date.UTC(Number(y), Number(m) - 1, Number(d))),
  );
  return `${month} ${Number(d)}, ${y}`;
}

export function signClass(value: number): string {
  if (value > 0) return "text-positive";
  if (value < 0) return "text-negative";
  return "";
}
