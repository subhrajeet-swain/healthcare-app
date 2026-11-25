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

export const STALL_MS = 3 * 60_000;

/** Nothing has moved for 3 minutes: time to tell the patient, gently.
 * ponytail: compares server step times with the phone clock; a skewed clock only shifts
 * when the note appears. Send a server-side flag if that ever matters. */
export function isStalled(steps: { at: string }[], now: number): boolean {
  const last = Math.max(...steps.map((s) => Date.parse(s.at)));
  return Number.isFinite(last) && now - last > STALL_MS;
}
