import type { ReportSummary } from "./api";

export type Role = "patient" | "lab_staff" | "doctor" | "lab_admin" | "platform_admin";

export type Route =
  | { name: "login"; slug: string }
  | { name: "consent" }
  | { name: "report"; id: string }
  | { name: "chat" }
  | { name: "profile" }
  | { name: "home" };

const DASHBOARDS: Record<Role, string> = {
  patient: "Your reports",
  lab_staff: "Lab console",
  doctor: "Review queue",
  lab_admin: "Lab settings",
  platform_admin: "Platform",
};

export function dashboardFor(role: Role): string {
  return DASHBOARDS[role];
}

export function parseRoute(path: string): Route {
  const login = path.match(/^\/([a-z0-9-]+)\/login\/?$/);
  if (login) return { name: "login", slug: login[1] };
  if (path === "/consent") return { name: "consent" };
  if (/^\/chat\/?$/.test(path)) return { name: "chat" };
  if (/^\/profile\/?$/.test(path)) return { name: "profile" };
  const report = path.match(/^\/reports\/([A-Za-z0-9-]+)\/?$/);
  if (report) return { name: "report", id: report[1] };
  return { name: "home" };
}

export function go(path: string): void {
  history.pushState(null, "", path);
  scrollTo(0, 0); // a new page starts at the top; Back keeps the browser's own restore
  dispatchEvent(new PopStateEvent("popstate"));
}

/** The report the Chat tab opens: the first one chat accepts (ready or in review), in the
 * server's order (newest report date first), so it matches the top of the Reports list. */
export function latestReady(reports: ReportSummary[]): ReportSummary | undefined {
  return reports.find((r) => r.status === "ready" || r.status === "needs_review");
}
