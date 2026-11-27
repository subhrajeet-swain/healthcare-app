import type { ReportSummary } from "./api";

export type Role = "patient" | "lab_staff" | "doctor" | "lab_admin" | "platform_admin";

export type Route =
  | { name: "login"; slug: string }
  | { name: "consent" }
  | { name: "report"; id: string }
  | { name: "review"; id: string }
  | { name: "chat" }
  | { name: "timeline" }
  | { name: "profile" }
  | { name: "shared"; slug: string; token: string } // a doctor's link: no session
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
  if (/^\/timeline\/?$/.test(path)) return { name: "timeline" };
  if (/^\/profile\/?$/.test(path)) return { name: "profile" };
  const shared = path.match(/^\/s\/([a-z0-9-]+)\/([A-Za-z0-9_-]+)\/?$/);
  if (shared) return { name: "shared", slug: shared[1], token: shared[2] };
  const report = path.match(/^\/reports\/([A-Za-z0-9-]+)\/?$/);
  if (report) return { name: "report", id: report[1] };
  const review = path.match(/^\/reviews\/([A-Za-z0-9-]+)\/?$/);
  if (review) return { name: "review", id: review[1] };
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
