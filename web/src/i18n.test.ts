import { describe, expect, it } from "vitest";
import { ApiError, messageFor } from "./api";
import { STRINGS, translate } from "./i18n";
import { FLAG, NEXT, STATUS, TRIAGE } from "./words";

describe("i18n", () => {
  it("has English and Hindi for every string", () => {
    for (const table of [STRINGS, STATUS, FLAG, TRIAGE, NEXT]) {
      for (const [key, pair] of Object.entries(table)) {
        expect(pair.en.trim(), key).not.toBe("");
        expect(pair.hi.trim(), key).not.toBe("");
        expect(/[\u0900-\u097F]/.test(pair.hi), key).toBe(true);
      }
    }
  });
  it("fills placeholders", () => {
    expect(translate("en", "codeHint", { last4: "3210" })).toContain("ending 3210");
    expect(translate("hi", "codeHint", { last4: "3210" })).toContain("3210");
  });
  it("gives error messages in the chosen language", () => {
    const e = new ApiError(415, "unsupported_file");
    expect(messageFor(e, "en")).toContain("PDF, JPG or PNG");
    expect(messageFor(e, "hi")).toMatch(/[\u0900-\u097F]/);
    expect(messageFor(new Error("x"), "hi")).toMatch(/[\u0900-\u097F]/);
  });
});

describe("chat errors", () => {
  it("are localised", () => {
    expect(messageFor(new ApiError(429, "too_many_messages"), "en")).toContain("30");
    expect(messageFor(new ApiError(409, "report_not_ready"), "hi")).toMatch(/[\u0900-\u097F]/);
  });
});
