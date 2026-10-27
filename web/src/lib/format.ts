export function money(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `A$${Number.isInteger(n) ? n.toString() : n.toFixed(2)}`;
}

export function pct(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${Math.round(n)}%` : "—";
}

/** "18 sec ago", "5 min ago", "2 h ago", "3 d ago"; "—" when unknown. */
export function ago(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "—";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "—";
  const s = Math.max(0, Math.floor((now - then) / 1000));
  if (s < 60) return `${s} sec ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export const GRADE_LABEL: Record<string, string> = {
  EXTREME: "Extreme",
  VERY_GOOD: "Very good",
  GOOD: "Good",
  NORMAL: "Normal",
  IGNORE: "Skip",
};

export const VERDICT_LABEL: Record<string, string> = {
  GENUINE: "Genuine discount",
  MISLEADING: "Misleading discount",
  NO_CLAIM: "No discount claimed",
  UNVERIFIED: "Not enough history to verify",
};

export const ALERT_LABEL: Record<string, string> = {
  TARGET_PRICE_HIT: "Target hit",
  PRICE_DROP: "Price drop",
  HISTORICAL_LOW: "Historical low",
  RESTOCK: "Restock",
  LOW_STOCK: "Low stock",
  FLASH_DEAL: "Flash deal",
};

export function stockLabel(stock: string | null | undefined): string {
  return (stock ?? "UNKNOWN").replace(/_/g, " ").toLowerCase();
}
