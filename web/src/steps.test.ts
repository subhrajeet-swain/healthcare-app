import { describe, expect, it } from "vitest";
import { stepStates } from "./steps";
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
