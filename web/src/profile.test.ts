import { afterEach, describe, expect, it, vi } from "vitest";
import { api, setProfile } from "./api";

function headersOf(call: unknown[]): Record<string, string> {
  return ((call[1] as RequestInit).headers ?? {}) as Record<string, string>;
}

describe("acting for a family member", () => {
  afterEach(() => {
    setProfile(null);
    vi.unstubAllGlobals();
  });

  it("puts the profile on browser-fetched URLs, only when one is chosen", () => {
    expect(api.fileUrl("r1")).toBe("/api/reports/r1/file");
    setProfile("m 1");
    expect(api.fileUrl("r1")).toBe("/api/reports/r1/file?profile=m%201");
    expect(api.eventsUrl("r1")).toBe("/api/reports/r1/events?profile=m%201");
    expect(api.exportUrl).toBe("/api/me/export"); // personal: never a profile
  });

  it("sends X-Profile on data calls and never on personal ones", async () => {
    const fetch = vi.fn(async () => new Response("[]", { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    setProfile("m1");
    await api.reports();
    await api.me();
    await api.family();
    await api.grantConsent();
    await api.deleteMe().catch(() => undefined);
    expect(headersOf(fetch.mock.calls[0])["X-Profile"]).toBe("m1");
    for (const call of fetch.mock.calls.slice(1)) expect(headersOf(call)["X-Profile"]).toBeUndefined();
  });
});
