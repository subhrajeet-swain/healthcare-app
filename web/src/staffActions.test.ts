import { describe, expect, it } from "vitest";
import { staffActions } from "./staffActions";

describe("staffActions", () => {
  it("offers mark-in-lab and upload after the sample is collected", () => {
    expect(staffActions("sample_collected")).toEqual({ markInLab: true, upload: true });
  });
  it("offers only upload while in the lab", () => {
    expect(staffActions("in_lab")).toEqual({ markInLab: false, upload: true });
  });
  it("offers nothing once the report is in the pipeline or done", () => {
    for (const s of ["received", "extracting", "explaining", "ready", "needs_review", "failed"] as const) {
      expect(staffActions(s)).toEqual({ markInLab: false, upload: false });
    }
  });
});
