import { describe, expect, it } from "vitest";
import { dashboardFor, parseRoute } from "./routes";

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
