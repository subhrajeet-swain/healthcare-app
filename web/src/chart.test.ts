import { describe, expect, it } from "vitest";
import { PAD, scale, shown } from "./chart";

const W = 320;
const H = 180;
const top = PAD.t;
const bottom = H - PAD.b;
const left = PAD.l;
const right = W - PAD.r;
const pt = (observed_on: string, value: number, ref_low: number | null = null, ref_high: number | null = null) => ({
  observed_on,
  value,
  ref_low,
  ref_high,
});

describe("scale", () => {
  it("maps the lowest value to the bottom edge and the highest to the top, inside the padding", () => {
    const { dots } = scale([pt("2026-01-01", 5), pt("2026-02-01", 10), pt("2026-03-01", 7.5)], W, H);
    expect(dots[0].y).toBeCloseTo(bottom);
    expect(dots[1].y).toBeCloseTo(top);
    expect(dots[2].y).toBeCloseTo((top + bottom) / 2);
    expect(dots[0].x).toBeCloseTo(left);
    expect(dots[2].x).toBeCloseTo(right);
  });

  it("spaces dots by date, not by count", () => {
    const { dots } = scale([pt("2026-01-01", 1), pt("2026-01-11", 2), pt("2026-01-31", 3)], W, H);
    const span = right - left;
    expect(dots[1].x).toBeCloseTo(left + span / 3);
  });

  it("spreads points that share one date evenly", () => {
    const { dots } = scale([pt("2026-01-01", 1), pt("2026-01-01", 2), pt("2026-01-01", 3)], W, H);
    expect(dots.map((d) => d.x)).toEqual([left, (left + right) / 2, right]);
  });

  it("centres a single point", () => {
    const { dots, band, yTicks } = scale([pt("2026-01-01", 7)], W, H);
    expect(dots).toEqual([{ x: (left + right) / 2, y: (top + bottom) / 2 }]);
    expect(band).toBeNull();
    expect(yTicks).toEqual([7]);
  });

  it("has no band when the latest point has no range", () => {
    // an older range does not make a band: only the latest point's does
    const { band } = scale([pt("2026-01-01", 5, 4, 8), pt("2026-02-01", 6)], W, H);
    expect(band).toBeNull();
  });

  it("draws the band from the latest point's range and keeps it inside the chart", () => {
    // domain is 4..10: the range 4..8 sits at the bottom, values above it
    const { dots, band } = scale([pt("2026-01-01", 5, 1, 2), pt("2026-02-01", 10, 4, 8)], W, H);
    expect(dots[1].y).toBeCloseTo(top);
    expect(band).not.toBeNull();
    const unit = (bottom - top) / 6;
    expect(band!.y).toBeCloseTo(top + 2 * unit); // 8 is two units under 10
    expect(band!.h).toBeCloseTo(4 * unit);
    expect(band!.y + band!.h).toBeCloseTo(bottom); // 4 is the lowest thing on the chart
  });

  it("stretches the domain to a range that lies beyond every value", () => {
    const { dots, band } = scale([pt("2026-01-01", 90), pt("2026-02-01", 95, 70, 100)], W, H);
    expect(band!.y).toBeCloseTo(top); // 100 is the top
    expect(band!.y + band!.h).toBeCloseTo(bottom); // 70 is the bottom
    expect(dots[0].y).toBeGreaterThan(top);
    expect(dots[1].y).toBeGreaterThan(top);
  });

  it("runs a one-sided range to the edge of the chart", () => {
    const upper = scale([pt("2026-01-01", 3), pt("2026-02-01", 9, null, 6)], W, H).band!;
    expect(upper.y).toBeCloseTo(top + (bottom - top) / 2); // 6 is half way between 3 and 9
    expect(upper.y + upper.h).toBeCloseTo(bottom); // open below: down to the bottom
    const lower = scale([pt("2026-01-01", 3), pt("2026-02-01", 9, 6, null)], W, H).band!;
    expect(lower.y).toBeCloseTo(top); // open above: up to the top
    expect(lower.y + lower.h).toBeCloseTo(top + (bottom - top) / 2);
  });

  it("gives min, middle and max ticks that line up with the dots", () => {
    const s = scale([pt("2026-01-01", 5), pt("2026-02-01", 10)], W, H);
    expect(s.yTicks).toEqual([5, 7.5, 10]);
    expect(s.tickY[0]).toBeCloseTo(s.dots[0].y);
    expect(s.tickY[2]).toBeCloseTo(s.dots[1].y);
  });

  it("returns nothing for no points", () => {
    expect(scale([], W, H)).toEqual({ dots: [], band: null, yTicks: [], tickY: [] });
  });
});

describe("scale with a wider left margin", () => {
  it("moves the plot, not the right edge, so long tick labels fit", () => {
    const { dots } = scale([pt("2026-01-01", 5), pt("2026-02-01", 10)], W, H, 70);
    expect(dots[0].x).toBe(70);
    expect(dots[1].x).toBe(right);
  });
});

describe("shown", () => {
  it("keeps the digits a reader can use: whole numbers from 100, one decimal from 1, two below", () => {
    expect(shown(245000)).toBe("2,45,000");
    expect(shown(100.93)).toBe("101");
    expect(shown(122.5)).toBe("123");
    expect(shown(6.84)).toBe("6.8");
    expect(shown(7)).toBe("7");
    expect(shown(0.847)).toBe("0.85");
    expect(shown(-3.26)).toBe("-3.3");
  });
});
