import { describe, expect, it } from "vitest";
import { dashboardFor, latestReady, parseRoute } from "./routes";

describe("dashboardFor", () => {
  it("maps every role to its dashboard heading", () => {
    expect(dashboardFor("patient")).toBe("Your reports");
    expect(dashboardFor("lab_staff")).toBe("Lab console");
    expect(dashboardFor("doctor")).toBe("Review queue");
    expect(dashboardFor("lab_admin")).toBe("Lab settings");
    expect(dashboardFor("platform_admin")).toBe("Platform");
  });
});

describe("parseRoute", () => {
  it("reads the lab slug from the login path", () => {
    expect(parseRoute("/lab-alpha/login")).toEqual({ name: "login", slug: "lab-alpha" });
  });
  it("recognises consent and home", () => {
    expect(parseRoute("/consent")).toEqual({ name: "consent" });
    expect(parseRoute("/")).toEqual({ name: "home" });
  });
  it("sends unknown paths home", () => {
    expect(parseRoute("/nope/x/y")).toEqual({ name: "home" });
  });
});

describe("report route", () => {
  it("reads the report id", () => {
    expect(parseRoute("/reports/0b9f-12")).toEqual({ name: "report", id: "0b9f-12" });
    expect(parseRoute("/reports/abc/")).toEqual({ name: "report", id: "abc" });
  });
  it("rejects ids with odd characters", () => {
    expect(parseRoute("/reports/../x")).toEqual({ name: "home" });
  });
});

describe("review route", () => {
  it("reads the review item id", () => {
    expect(parseRoute("/reviews/3f2a-9c")).toEqual({ name: "review", id: "3f2a-9c" });
    expect(parseRoute("/reviews/3f2a/")).toEqual({ name: "review", id: "3f2a" });
  });
  it("rejects ids with odd characters", () => {
    expect(parseRoute("/reviews/../x")).toEqual({ name: "home" });
  });
});

describe("nav routes", () => {
  it("reads chat and profile", () => {
    expect(parseRoute("/chat")).toEqual({ name: "chat" });
    expect(parseRoute("/profile/")).toEqual({ name: "profile" });
  });
});

describe("latestReady", () => {
  const r = (id: string, status: string, created_at: string) => ({ id, status, created_at }) as never;
  it("picks the first report chat accepts, in list order (newest report date first)", () => {
    // uploaded last but collected in April: not the one the patient sees on top
    const list = [
      r("bad", "failed", "2026-11-25T16:02:00Z"),
      r("nov20", "needs_review", "2026-11-25T16:18:00Z"),
      r("busy", "extracting", "2026-11-25T16:20:00Z"),
      r("apr", "needs_review", "2026-11-25T16:35:00Z"),
    ];
    expect(latestReady(list)?.id).toBe("nov20");
  });
  it("is undefined when nothing is ready", () => {
    expect(latestReady([r("busy", "received", "2026-11-20T00:00:00Z")])).toBeUndefined();
    expect(latestReady([])).toBeUndefined();
  });
});
