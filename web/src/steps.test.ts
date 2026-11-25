import { describe, expect, it } from "vitest";
import { isStalled, stepStates } from "./steps";
import { fmt } from "./words";

describe("fmt", () => {
  it("groups digits the Indian way", () => {
    expect(fmt(245000)).toBe("2,45,000");
    expect(fmt(11.2)).toBe("11.2");
    expect(fmt(1050)).toBe("1,050");
  });
});

describe("stepStates", () => {
  it("marks done, now and later", () => {
    expect(stepStates("extracting", "patient")).toEqual([
      ["received", "done"],
      ["extracting", "now"],
      ["explaining", "later"],
      ["ready", "later"],
    ]);
  });
  it("marks every step done when ready or in review", () => {
    for (const s of ["ready", "needs_review"] as const) {
      expect(stepStates(s, "patient").every(([, st]) => st === "done")).toBe(true);
    }
  });
  it("shows a failed report as stopped on its last step", () => {
    expect(stepStates("failed", "patient").at(-1)).toEqual(["failed", "stopped"]);
  });
  it("starts lab reports at sample collection", () => {
    expect(stepStates("in_lab", "lab").slice(0, 3)).toEqual([
      ["sample_collected", "done"],
      ["in_lab", "now"],
      ["received", "later"],
    ]);
  });
});

describe("isStalled", () => {
  const at = (iso: string) => ({ at: iso });
  const t0 = Date.parse("2026-11-26T10:00:00Z");
  it("waits 3 minutes after the last step before saying so", () => {
    const steps = [at("2026-11-26T09:58:00Z"), at("2026-11-26T09:59:00Z")];
    expect(isStalled(steps, t0)).toBe(false);
    expect(isStalled(steps, t0 + 2 * 60_000 + 1)).toBe(true);
  });
  it("uses the latest step, whatever the order", () => {
    expect(isStalled([at("2026-11-26T09:59:30Z"), at("2026-11-26T09:00:00Z")], t0)).toBe(false);
  });
  it("says nothing without steps or with a bad date", () => {
    expect(isStalled([], t0)).toBe(false);
    expect(isStalled([at("garbage")], t0)).toBe(false);
  });
});
