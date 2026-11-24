export type Role = "patient" | "lab_staff" | "doctor" | "lab_admin" | "platform_admin";

export type Route = { name: "login"; slug: string } | { name: "consent" } | { name: "home" };

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
  return { name: "home" };
}

export function go(path: string): void {
  history.pushState(null, "", path);
  dispatchEvent(new PopStateEvent("popstate"));
}
