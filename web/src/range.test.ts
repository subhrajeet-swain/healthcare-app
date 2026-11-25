import { describe, expect, it } from "vitest";
import { rangePosition } from "./range";

describe("rangePosition", () => {
  it("places the normal zone in the middle half for a two-sided range", () => {
    const r = rangePosition(15, 13, 17);
    expect(r.zone).toEqual([25, 75]);
    expect(r.side).toBe("within");
    expect(r.pct).toBeCloseTo(50);
  });
  it("marks below and above", () => {
    expect(rangePosition(11, 13, 17).side).toBe("below");
    expect(rangePosition(11, 13, 17).pct).toBeCloseTo(0);
    expect(rangePosition(18, 13, 17).side).toBe("above");
    expect(rangePosition(18, 13, 17).pct).toBeCloseTo(87.5);
  });
  it("treats the bounds as inside the range", () => {
    expect(rangePosition(13, 13, 17).side).toBe("within");
    expect(rangePosition(17, 13, 17).side).toBe("within");
  });
  it("clamps far-out values to the track", () => {
    expect(rangePosition(-50, 13, 17).pct).toBe(0);
    expect(rangePosition(500, 13, 17).pct).toBe(100);
  });
  it("handles an upper bound only", () => {
    const r = rangePosition(180, null, 100);
    expect(r.zone).toEqual([0, 50]);
    expect(r.side).toBe("above");
    expect(r.pct).toBeCloseTo(90);
  });
  it("handles a lower bound only", () => {
    const r = rangePosition(30, 40, null);
    expect(r.zone).toEqual([50, 100]);
    expect(r.side).toBe("below");
    expect(r.pct).toBeCloseTo(37.5);
  });
  it("has no zone when there is no range", () => {
    expect(rangePosition(5, null, null)).toEqual({ pct: 50, side: "within", zone: null });
  });
});
