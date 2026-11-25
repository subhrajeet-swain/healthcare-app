export type Side = "below" | "within" | "above";
export type Position = { pct: number; side: Side; zone: [number, number] | null };

const clamp = (n: number) => Math.min(100, Math.max(0, n));

/**
 * Where a value sits on a track whose shaded zone is the normal range.
 * Two-sided: the zone is the middle half. One-sided: the zone is one half, from 0 or to 2x the bound.
 */
export function rangePosition(value: number, low: number | null, high: number | null): Position {
  const side: Side =
    low !== null && value < low ? "below" : high !== null && value > high ? "above" : "within";
  if (low !== null && high !== null) {
    const span = high - low || Math.abs(high) || 1;
    const start = low - span / 2;
    return { pct: clamp(((value - start) / (span * 2)) * 100), side, zone: [25, 75] };
  }
  if (high !== null) return { pct: clamp((value / (2 * high)) * 100), side, zone: [0, 50] };
  if (low !== null) return { pct: clamp((value / (2 * low)) * 100), side, zone: [50, 100] };
  return { pct: 50, side, zone: null };
}
