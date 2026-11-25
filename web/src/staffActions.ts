import type { Status } from "./api";

/** What the lab console may do next with a report (the server enforces the same rules). */
export function staffActions(status: Status): { markInLab: boolean; upload: boolean } {
  return { markInLab: status === "sample_collected", upload: status === "sample_collected" || status === "in_lab" };
}
