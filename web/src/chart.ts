export type ChartPoint = {
  observed_on: string;
  value: number;
  ref_low: number | null;
  ref_high: number | null;
};
export type Scaled = {
  dots: { x: number; y: number }[];
  band: { y: number; h: number } | null;
  yTicks: number[]; // values: the lowest, the middle, the highest on the chart
  tickY: number[]; // where each tick sits, in the same units as the dots
};

/** Room the chart keeps free around its plot: the left holds the tick labels, the top the last value's label, the bottom the dates. */
export const PAD = { l: 44, r: 20, t: 36, b: 32 };

const NUM = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

/** A canonical value as a reader wants it: whole from 100, one decimal from 1, two below (en-IN grouping). */
export function shown(v: number): string {
  const a = Math.abs(v);
  const places = a >= 100 ? 0 : a >= 1 ? 1 : 2;
  return NUM.format(Number(v.toFixed(places)));
}

/**
 * Where a test's points sit in a `width` x `height` box. Time runs left to right by date (points
 * on one date spread evenly); the value axis runs from the lowest thing on the chart to the
 * highest, and that includes the latest point's range, so the band is never cut off. The band is
 * that latest range alone: older ranges came from older reports. A range with one bound runs to
 * the edge of the chart on its open side; no range at all means no band. `padLeft` widens the
 * left margin for tick labels longer than the default makes room for.
 */
export function scale(points: ChartPoint[], width: number, height: number, padLeft = PAD.l): Scaled {
  if (points.length === 0) return { dots: [], band: null, yTicks: [], tickY: [] };
  const plotW = width - padLeft - PAD.r;
  const plotH = height - PAD.t - PAD.b;
  const last = points[points.length - 1];

  const bounds = [last.ref_low, last.ref_high].filter((b): b is number => b !== null);
  const values = [...points.map((p) => p.value), ...bounds];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const y = (v: number) => (max === min ? PAD.t + plotH / 2 : PAD.t + ((max - v) / (max - min)) * plotH);

  const times = points.map((p) => Date.parse(p.observed_on));
  const first = Math.min(...times);
  const span = Math.max(...times) - first;
  const x = (i: number) => {
    if (points.length === 1) return padLeft + plotW / 2;
    return padLeft + (span > 0 ? ((times[i] - first) / span) * plotW : (i / (points.length - 1)) * plotW);
  };

  const dots = points.map((p, i) => ({ x: x(i), y: y(p.value) }));
  let band: Scaled["band"] = null;
  if (bounds.length > 0) {
    const top = y(last.ref_high ?? max);
    band = { y: top, h: y(last.ref_low ?? min) - top };
  }
  const yTicks = max === min ? [min] : [min, (min + max) / 2, max];
  return { dots, band, yTicks, tickY: yTicks.map(y) };
}
