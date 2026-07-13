/** Money in a fund UI must never be ambiguous — always show the unit, always tabular. */
export function money(v: number | null | undefined, currency = "SAR"): string {
  if (v === null || v === undefined) return "—";
  const abs = Math.abs(v);
  if (abs >= 1_000_000_000) return `${currency} ${(v / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${currency} ${(v / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${currency} ${(v / 1_000).toFixed(0)}K`;
  return `${currency} ${v.toFixed(0)}`;
}

export function moneyFull(v: number | null | undefined, currency = "SAR"): string {
  if (v === null || v === undefined) return "—";
  return `${currency} ${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export function num(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString("en-US", { maximumFractionDigits: digits });
}

export function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${v.toFixed(0)}%`;
}

export function date(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function area(km2: number | null | undefined): string {
  if (km2 === null || km2 === undefined) return "—";
  if (km2 < 1) return `${(km2 * 100).toFixed(0)} ha`;
  return `${num(km2, km2 < 100 ? 1 : 0)} km²`;
}
