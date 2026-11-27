import type { ReportSummary, Result, SharedReport, Statement, Triage } from "./api";
import type { Lang } from "./i18n";

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

/** The explanation a report page prints. The closing advice is the NEXT tag above it, so it is not
 * printed twice. With the red banner showing, the urgent line the pipeline stores first (a system
 * statement on an urgent report) is left out too: the banner already says it. */
export function explanationLines(
  report: Pick<SharedReport, "explanations" | "next_step" | "urgent">,
  lang: Lang,
  banner: boolean,
): Statement[] {
  const all = (report.explanations?.[lang] ?? report.explanations?.en)?.statements ?? [];
  return all.filter(
    (s, i) =>
      !(banner && i === 0 && report.urgent && s.source === "system") &&
      !(report.next_step !== "no_action" && s.source === "system" && i === all.length - 1 && i > 0),
  );
}
