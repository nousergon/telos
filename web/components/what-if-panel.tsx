"use client";

import { useCallback, useEffect, useState } from "react";
import { accountingMoneyWhole, moneyWhole, percent } from "@/lib/format";
import type { AdjustmentsDetail, DeductionDetail, IncomeSourceDetail } from "@/lib/types";
import { Section, StatCard } from "@/components/ui";

type OverrideState = {
  enabled: boolean;
  values: Record<string, string>; // field key -> user-entered value (empty for null)
  saving: boolean;
  dirty: boolean;
};

export function WhatIfPanel({
  sources,
  deduction,
  adjustments,
  baseAgi,
  baseTaxable,
  baseTotalTax,
  marginalRate,
  effectiveRate,
  ccy = "USD",
}: {
  sources: IncomeSourceDetail | null | undefined;
  deduction: DeductionDetail | null | undefined;
  adjustments: AdjustmentsDetail | null | undefined;
  baseAgi: number;
  baseTaxable: number;
  baseTotalTax: number;
  marginalRate: number;
  effectiveRate: number;
  ccy?: string;
}) {
  const [overrides, setOverrides] = useState<OverrideState>({
    enabled: false,
    values: {},
    saving: false,
    dirty: false,
  });

  // Load existing overrides on mount
  useEffect(() => {
    fetch("/dash/api/adjustments")
      .then((r) => r.json())
      .then((data) => {
        if (data.ok && data.overrides && typeof data.overrides === "object") {
          const vals: Record<string, string> = {};
          for (const [k, v] of Object.entries(data.overrides)) {
            if (typeof v === "number") {
              vals[k] = String(v);
            }
          }
          const hasOverrides = Object.keys(vals).length > 0;
          setOverrides({
            enabled: hasOverrides,
            values: vals,
            saving: false,
            dirty: false,
          });
        }
      })
      .catch(() => { /* overrides are optional */ });
  }, []);

  const setOverride = useCallback((key: string, raw: string) => {
    setOverrides((prev) => ({
      ...prev,
      values: { ...prev.values, [key]: raw },
      dirty: true,
    }));
  }, []);

  const clearOverride = useCallback((key: string) => {
    setOverrides((prev) => {
      const next = { ...prev.values };
      delete next[key];
      return { ...prev, values: next, dirty: true };
    });
  }, []);

  const saveOverrides = useCallback(async () => {
    setOverrides((prev) => ({ ...prev, saving: true }));
    const payload: Record<string, number | null> = {};
    for (const [k, v] of Object.entries(overrides.values)) {
      const trimmed = v.trim();
      if (trimmed === "") {
        payload[k] = null;
      } else {
        const n = Number(trimmed);
        if (Number.isFinite(n)) {
          payload[k] = n;
        }
      }
    }
    try {
      const resp = await fetch("/dash/api/adjustments", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (data.ok) {
        setOverrides((prev) => ({ ...prev, saving: false, dirty: false, enabled: true }));
      } else {
        setOverrides((prev) => ({ ...prev, saving: false }));
      }
    } catch {
      setOverrides((prev) => ({ ...prev, saving: false }));
    }
  }, [overrides.values]);

  const clearAll = useCallback(async () => {
    setOverrides((prev) => ({ ...prev, saving: true }));
    try {
      await fetch("/dash/api/adjustments", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      setOverrides({ enabled: false, values: {}, saving: false, dirty: false });
    } catch {
      setOverrides((prev) => ({ ...prev, saving: false }));
    }
  }, []);

  const getAdj = useCallback(
    (key: string, base: number): number => {
      if (!overrides.enabled && !overrides.dirty) return base;
      const raw = overrides.values[key];
      if (raw === undefined || raw.trim() === "") return base;
      const n = Number(raw);
      return Number.isFinite(n) ? n : base;
    },
    [overrides.enabled, overrides.dirty, overrides.values],
  );

  if (!sources) {
    return null;
  }

  // Income components
  const comps: { key: string; label: string; base: number }[] = [
    { key: "wages", label: "Wages", base: Number(sources.wages) },
    { key: "interest", label: "Interest", base: Number(sources.interest) },
    { key: "ordinary_dividends", label: "Dividends", base: Number(sources.ordinary_dividends) },
    { key: "net_capital_gain", label: "Capital gains", base: Number(sources.net_capital_gain) },
    { key: "schedule_e_total", label: "Schedule E (rental)", base: Number(sources.schedule_e_total) },
    { key: "other_income_total", label: "Other income", base: Number(sources.other_income_total) },
  ];

  // Schedule E per-property overrides
  const scheProps = (sources.schedule_e_properties ?? []).filter(
    (p) => Number(p.net_income) !== 0,
  );
  for (const p of scheProps) {
    comps.push({
      key: `sche_e:${p.arrangement_id}`,
      label: `  ${p.property_name}`,
      base: Number(p.net_income),
    });
  }

  // Above-the-line deduction components
  const adjComps: { key: string; label: string; base: number }[] = [];
  const adjItems = adjustments?.items ?? [];
  for (const item of adjItems) {
    const baseVal = Number(item.amount);
    if (baseVal > 0) {
      adjComps.push({
        key: `adjust:${item.name}`,
        label: `  − ${item.name}`,
        base: baseVal,
      });
    }
  }

  // Adjusted values
  const adjustedIncome = comps.reduce((sum, c) => sum + getAdj(c.key, c.base), 0);
  const adjustedAdjTotal = adjComps.reduce((sum, c) => sum + getAdj(c.key, c.base), 0);
  const adjustedAgi = Math.max(adjustedIncome - adjustedAdjTotal, 0);
  const adjDeduction =
    deduction && Number(deduction.itemized_total) > 0
      ? Math.max(Number(deduction.standard_amount), Number(deduction.itemized_total))
      : deduction
        ? Number(deduction.standard_amount)
        : 0;
  const adjQbi = deduction ? Number(deduction.qbi) : 0;
  const adjustedTaxable = Math.max(adjustedAgi - adjDeduction - adjQbi, 0);
  const taxDelta = baseTaxable > 0
    ? (adjustedTaxable - baseTaxable) * marginalRate
    : adjustedTaxable * effectiveRate;
  const adjustedTax = Math.max(baseTotalTax + taxDelta, 0);

  const hasChanges = Object.values(overrides.values).some((v) => v.trim() !== "");
  const showAdjSection = adjComps.length > 0 || Object.keys(overrides.values).some((k) => k.startsWith("adjust:"));

  return (
    <Section title="What-if adjustments" note="override income or solopreneur deductions — tax recalculated">
      {!hasChanges && !overrides.enabled && (
        <p className="mb-3 text-xs text-muted">
          No adjustments saved. Enter overrides below, then save to persist.
        </p>
      )}

      {overrides.enabled && !overrides.dirty && hasChanges && (
        <div className="mb-3 rounded-md border border-accent/30 bg-accent/5 px-4 py-2 text-sm">
          Adjustments active — base values overridden.{" "}
          <button
            onClick={clearAll}
            className="text-xs text-muted underline hover:text-ink"
            disabled={overrides.saving}
          >
            Clear all adjustments
          </button>
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line bg-surface text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Component</th>
              <th className="px-4 py-2 text-right font-medium">Base</th>
              <th className="px-4 py-2 text-right font-medium">Override</th>
            </tr>
          </thead>
          <tbody>
            {/* Income rows */}
            {comps
              .filter((c) => c.base !== 0 || overrides.values[c.key] !== undefined)
              .map((c) => (
                <tr key={c.key} className="border-b border-line">
                  <td className="px-4 py-2 text-sm">{c.label}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-muted">
                    {moneyWhole(c.base, ccy)}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <OverrideInput
                      key_={c.key}
                      value={overrides.values[c.key] ?? ""}
                      base={c.base}
                      ccy={ccy}
                      onChange={setOverride}
                      onClear={clearOverride}
                    />
                  </td>
                </tr>
              ))}

            {/* Total income */}
            <tr className="border-b border-line">
              <td className="px-4 py-2 text-xs font-semibold uppercase tracking-wide">
                Total income
              </td>
              <td className="px-4 py-2 text-right text-sm font-semibold tabular-nums">
                {moneyWhole(baseAgi + (adjustments?.total ? Number(adjustments.total) : 0), ccy)}
              </td>
              <td className="px-4 py-2 text-right text-sm font-semibold tabular-nums">
                {moneyWhole(adjustedIncome, ccy)}
              </td>
            </tr>

            {/* Above-the-line deductions */}
            {showAdjSection && (
              <tr className="border-b border-line bg-accent/[0.03]">
                <td className="px-4 py-2" colSpan={3}>
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-accent">
                    Above-the-line deductions (Schedule 1 Part II)
                  </span>
                </td>
              </tr>
            )}
            {adjComps
              .filter((c) => c.base !== 0 || overrides.values[c.key] !== undefined)
              .map((c) => {
                const adj = getAdj(c.key, c.base);
                return (
                  <tr key={c.key} className="border-b border-line bg-accent/[0.03]">
                    <td className="px-4 py-2 text-sm text-accent">{c.label}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-muted">
                      ({moneyWhole(c.base, ccy)})
                    </td>
                    <td className="px-4 py-2 text-right">
                      <OverrideInput
                        key_={c.key}
                        value={overrides.values[c.key] ?? ""}
                        base={c.base}
                        ccy={ccy}
                        onChange={setOverride}
                        onClear={clearOverride}
                      />
                    </td>
                  </tr>
                );
              })}

            {/* AGI row */}
            <tr className="border-t-2 border-line">
              <td className="px-4 py-2 text-xs font-semibold uppercase tracking-wide">
                Adjusted gross income (AGI)
              </td>
              <td className="px-4 py-2 text-right text-base font-semibold tabular-nums">
                {moneyWhole(baseAgi, ccy)}
              </td>
              <td className="px-4 py-2 text-right text-base font-semibold tabular-nums">
                {moneyWhole(adjustedAgi, ccy)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* What-if summary */}
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Adjusted AGI"
          value={moneyWhole(adjustedAgi, ccy)}
          hint={adjustedAgi !== baseAgi ? `${signText(adjustedAgi - baseAgi)} vs base` : undefined}
        />
        <StatCard
          label="Adj. taxable income"
          value={moneyWhole(adjustedTaxable, ccy)}
          hint={`deduction ${moneyWhole(adjDeduction, ccy)} + QBI ${moneyWhole(adjQbi, ccy)}`}
        />
        <StatCard
          label="Estimated tax"
          value={accountingMoneyWhole(adjustedTax, ccy)}
          hint={baseTotalTax > 0 ? `~${percent(taxDelta / baseTotalTax)} vs base` : undefined}
          valueClass={adjustedTax > baseTotalTax ? "text-negative" : adjustedTax < baseTotalTax ? "text-positive" : ""}
        />
        <StatCard
          label="Delta vs base"
          value={`${adjustedTax >= baseTotalTax ? "+" : ""}${moneyWhole(Math.abs(adjustedTax - baseTotalTax), ccy)}`}
          valueClass={adjustedTax >= baseTotalTax ? "text-negative" : "text-positive"}
          hint={`at marginal rate ${percent(marginalRate)}`}
        />
      </div>

      <div className="mt-3 flex items-center gap-3">
        <button
          onClick={saveOverrides}
          disabled={overrides.saving || !overrides.dirty}
          className="rounded-md bg-ink px-4 py-2 text-xs font-medium text-white transition hover:bg-ink/80 disabled:opacity-40"
        >
          {overrides.saving ? "Saving…" : overrides.dirty ? "Save adjustments" : "Saved"}
        </button>
        <span className="text-[10px] text-muted">
          Saved adjustments persist across sessions. Re-run{" "}
          <code className="rounded bg-surface px-1">telos.planning</code> for a fully recomputed
          projection incorporating manual changes.
        </span>
      </div>
    </Section>
  );
}

function OverrideInput({
  key_,
  value,
  base,
  ccy,
  onChange,
  onClear,
}: {
  key_: string;
  value: string;
  base: number;
  ccy: string;
  onChange: (key: string, raw: string) => void;
  onClear: (key: string) => void;
}) {
  return (
    <div className="flex items-center justify-end gap-1">
      <input
        type="text"
        inputMode="decimal"
        placeholder={moneyWhole(base, ccy)}
        value={value}
        onChange={(e) => onChange(key_, e.target.value)}
        className="w-28 rounded border border-line bg-surface px-2 py-1 text-right tabular-nums text-sm focus:border-accent focus:outline-none"
      />
      {value !== undefined && value !== "" && (
        <button
          onClick={() => onClear(key_)}
          className="text-xs text-muted hover:text-negative"
          title="Clear override"
        >
          ×
        </button>
      )}
    </div>
  );
}

function signText(delta: number): string {
  if (delta > 0) return "+" + moneyWhole(delta);
  if (delta < 0) return moneyWhole(delta);
  return "";
}
