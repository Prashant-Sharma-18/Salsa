const moneyFormatter = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const numberFormatter = new Intl.NumberFormat("en-US");

/** Money is always integer cents from the API; divide only for display. */
export function formatMoney(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "—";
  return moneyFormatter.format(cents / 100);
}

export function formatNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return numberFormatter.format(n);
}

export function formatPoints(n: number, signed = false): string {
  const s = numberFormatter.format(Math.abs(n));
  if (!signed) return `${n < 0 ? "-" : ""}${s}`;
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${s}`;
}

/** Render a UTC ISO timestamp in the viewer's chosen IANA timezone. */
export function formatDateTime(iso: string | null | undefined, timeZone?: string): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("en-US", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone,
    }).format(new Date(iso));
  } catch {
    return new Date(iso).toLocaleString();
  }
}

export function formatDate(iso: string | null | undefined, timeZone?: string): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeZone }).format(new Date(iso));
  } catch {
    return new Date(iso).toLocaleDateString();
  }
}

/** "12.50" for an input field from cents. */
export function centsToInput(cents: number | null | undefined): string {
  if (!cents) return "";
  return (cents / 100).toFixed(2);
}

export const ENTRY_LABELS: Record<string, string> = {
  award: "Purchase points",
  redemption: "Reward redeemed",
  reversal: "Reversal",
  adjustment: "Manual adjustment",
  expiration: "Expired",
  referral_bonus: "Referral bonus",
  birthday_bonus: "Birthday bonus",
};

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** Plain-language schedule, e.g. "Tue & Thu · Oct 1 – Oct 31, 2026". */
export function promotionSchedule(p: { days_of_week: number[]; starts_on: string; ends_on: string | null }): string {
  const days = p.days_of_week.length === 0 || p.days_of_week.length === 7 ? "Every day" : p.days_of_week.map((d) => WEEKDAYS[d]).join(" & ");
  const fmt = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  return `${days} · from ${fmt(p.starts_on)}${p.ends_on ? ` to ${fmt(p.ends_on)}` : ""}`;
}

export function promotionValue(p: { promo_type: string; multiplier_percent: number | null; bonus_points: number | null }): string {
  return p.promo_type === "multiplier" ? `${(p.multiplier_percent ?? 100) / 100}x points` : `+${p.bonus_points} bonus points`;
}

export const REFERRAL_LABELS: Record<string, string> = {
  created: "Invited",
  clicked: "Clicked",
  signed_up: "Signed up",
  qualified: "Qualified",
  rewarded: "Rewarded",
  rejected: "Rejected",
};

export const REWARD_TYPE_LABELS: Record<string, string> = {
  fixed_discount: "Fixed discount",
  free_item: "Free item or service",
  custom: "Merchant-defined",
};

export function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return isoDate(d);
}
