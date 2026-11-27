import { describe, expect, it } from "vitest";
import { telHref, viaKey } from "./channels";

describe("telHref", () => {
  it("keeps digits and a leading +", () => {
    expect(telHref("+91 11 4000-0000")).toBe("tel:+911140000000");
  });
  it("is null with nothing to call", () => {
    expect(telHref("")).toBeNull();
    expect(telHref(null)).toBeNull();
  });
});

describe("viaKey", () => {
  it("tags the chat channels but not web", () => {
    expect(viaKey("telegram")).toBe("viaTelegram");
    expect(viaKey("whatsapp")).toBe("viaWhatsApp");
    expect(viaKey("web")).toBeNull();
    expect(viaKey(undefined)).toBeNull();
  });
});
