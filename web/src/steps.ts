import type { ReportDetail, Status } from "./api";

export type StepState = "done" | "now" | "later" | "stopped";

const PATIENT: Status[] = ["received", "extracting", "explaining", "ready"];
const LAB: Status[] = ["sample_collected", "in_lab", ...PATIENT];

/** The progress list: each step with the one word the patient reads for it. */
export function stepStates(status: Status, source: ReportDetail["source"]): [Status, StepState][] {
  const steps = source === "lab" ? LAB : PATIENT;
  if (status === "failed") {
    return steps.map((s, i) => (i === steps.length - 1 ? ["failed", "stopped"] : [s, "done"]));
  }
  const finished = status === "ready" || status === "needs_review";
  const current = finished ? steps.length : steps.indexOf(status);
  return steps.map((s, i) => [s, i < current ? "done" : i === current ? "now" : "later"]);
}
