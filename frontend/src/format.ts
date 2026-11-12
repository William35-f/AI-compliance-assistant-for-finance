// Number formatting shared by the pages.

const CURRENCY_PREFIX: Record<string, string> = { SGD: "S$", USD: "US$", HKD: "HK$" };

/** 22_900_000_000 -> "S$22.90 bn"; 149_455_000 -> "S$149.5 m". */
export function formatMoney(value: number | null, currency: string): string {
  if (value === null) return "–";
  const prefix = CURRENCY_PREFIX[currency] ?? `${currency} `;
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (abs >= 1e9) return `${sign}${prefix}${(abs / 1e9).toFixed(2)} bn`;
  if (abs >= 1e6) return `${sign}${prefix}${(abs / 1e6).toFixed(1)} m`;
  if (abs >= 1e3) return `${sign}${prefix}${(abs / 1e3).toFixed(1)} k`;
  return `${sign}${prefix}${abs.toLocaleString()}`;
}

/** The number exactly as printed in the report, with its unit label. */
export function formatAsReported(value: number | null, unit: string | null): string {
  if (value === null) return "–";
  const printed = value.toLocaleString("en-SG", { maximumFractionDigits: 2 });
  return unit ? `${printed} (${unit})` : printed;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "–";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  if (value === 0) return "$0";
  return value < 0.01 ? `$${value.toFixed(5)}` : `$${value.toFixed(3)}`;
}

export function formatRate(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return `${(value * 100).toFixed(1)}%`;
}
