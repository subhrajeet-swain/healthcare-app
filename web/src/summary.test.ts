import { describe, expect, it } from "vitest";
import type { ReportSummary } from "./api";
import { stateCounts, summarize } from "./summary";

const r = (over: Partial<ReportSummary>): ReportSummary => ({
  id: "x", status: "ready", triage: "green", source: "patient",
  created_at: "2026-11-20T00:00:00Z", collected_on: null, tests: null, ...over,
});

describe("summarize", () => {
  it("leads with the newest report and counts only what has been read", () => {
    const s = summarize([
      r({ id: "new", triage: "red", status: "needs_review", tests: "ALT (SGPT), HbA1c" }),
      r({ id: "busy", status: "extracting", triage: null, tests: null }),
      r({ id: "old", triage: "amber", tests: "Hemoglobin, Platelet Count, WBC Count" }),
      r({ id: "bad", status: "failed", triage: null }),
    ]);
    expect(s.latest?.id).toBe("new");
    expect(s.latestTests).toBe(2);
    expect(s).toMatchObject({ reports: 4, testsRead: 5, urgent: 1 });
  });
  it("handles an empty vault", () => {
    expect(summarize([])).toEqual({ latest: undefined, latestTests: 0, reports: 0, testsRead: 0, urgent: 0 });
  });
});

describe("stateCounts", () => {
  it("counts results per state, normal first and urgent last, skipping empty states", () => {
    const rs = [{ triage: "red" }, { triage: "green" }, { triage: "green" }, { triage: "red" }] as never;
    expect(stateCounts(rs)).toEqual([["green", 2], ["red", 2]]);
    expect(stateCounts([])).toEqual([]);
  });
});
