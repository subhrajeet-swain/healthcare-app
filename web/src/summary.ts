import type { ReportSummary, Result, Triage } from "./api";

export type Summary = {
  latest: ReportSummary | undefined;
  latestTests: number;
  reports: number;
  testsRead: number;
  urgent: number;
};

const read = (r: ReportSummary) => r.status === "ready" || r.status === "needs_review";
// the list carries test names joined by ", " (server string_agg); names never contain ", "
const count = (tests: string | null) => (tests ? tests.split(", ").length : 0);

/** The Reports home numbers. `reports` comes newest first from the server. */
export function summarize(reports: ReportSummary[]): Summary {
  const latest = reports[0];
  return {
    latest,
    latestTests: latest ? count(latest.tests) : 0,
    reports: reports.length,
    testsRead: reports.filter(read).reduce((n, r) => n + count(r.tests), 0),
    urgent: reports.filter((r) => read(r) && r.triage === "red").length,
  };
}

/** Result counts per state, for the word pills: normal first, urgent last; empty states left out. */
export function stateCounts(results: Pick<Result, "triage">[]): [Triage, number][] {
  return (["green", "amber", "red"] as const)
    .map((s): [Triage, number] => [s, results.filter((r) => r.triage === s).length])
    .filter(([, n]) => n > 0);
}
