import { describe, expect, it } from "vitest";
import { STRINGS } from "./i18n";
import { dueLabel, reasonTone, reasonWord, testLabel, trendLine } from "./review";

const NOW = new Date("2026-11-26T10:00:00Z");
const at = (ms: number) => new Date(NOW.getTime() + ms).toISOString();
const MIN = 60_000;
const HOUR = 60 * MIN;

describe("dueLabel", () => {
  it("counts down to a due time in the future", () => {
    expect(dueLabel(at(2 * HOUR), NOW)).toBe("due in 2 h");
    expect(dueLabel(at(45 * MIN), NOW)).toBe("due in 45 min");
    expect(dueLabel(at(3 * 24 * HOUR), NOW)).toBe("due in 3 d");
  });
  it("counts up from a due time already past", () => {
    expect(dueLabel(at(-15 * MIN), NOW)).toBe("overdue 15 min");
    expect(dueLabel(at(-5 * HOUR), NOW)).toBe("overdue 5 h");
    expect(dueLabel(at(-2 * 24 * HOUR), NOW)).toBe("overdue 2 d");
  });
  it("says due now inside a minute, either side", () => {
    expect(dueLabel(at(30_000), NOW)).toBe("due now");
    expect(dueLabel(at(-30_000), NOW)).toBe("due now");
    expect(dueLabel(at(0), NOW)).toBe("due now");
  });
  it("rounds down, so the first minute and hour read as 1", () => {
    expect(dueLabel(at(MIN), NOW)).toBe("due in 1 min");
    expect(dueLabel(at(90 * MIN), NOW)).toBe("due in 1 h");
    expect(dueLabel(at(-59 * MIN - 59_000), NOW)).toBe("overdue 59 min");
  });
  it("reads in Hindi when asked", () => {
    expect(dueLabel(at(2 * HOUR), NOW, "hi")).toMatch(/[ऀ-ॿ]/);
    expect(dueLabel(at(-15 * MIN), NOW, "hi")).toContain("15");
    expect(dueLabel(at(0), NOW, "hi")).toMatch(/[ऀ-ॿ]/);
  });
  it("does not guess at a date it cannot read", () => {
    expect(dueLabel("not a date", NOW)).toBe("");
  });
});

describe("reasonWord", () => {
  it("names all four reasons", () => {
    expect(reasonWord("red")).toBe("Urgent result");
    expect(reasonWord("warnings")).toBe("Check the reading");
    expect(reasonWord("trend")).toBe("Trend");
    expect(reasonWord("gated_answer")).toBe("Chat answer");
  });
  it("has a Hindi word for each", () => {
    for (const r of ["red", "warnings", "trend", "gated_answer"] as const) {
      expect(reasonWord(r, "hi")).toMatch(/[ऀ-ॿ]/);
    }
  });
});

describe("reasonTone", () => {
  it("colours red as red, the soft reasons amber, a chat answer neutral", () => {
    expect(reasonTone("red")).toBe("red");
    expect(reasonTone("warnings")).toBe("amber");
    expect(reasonTone("trend")).toBe("amber");
    expect(reasonTone("gated_answer")).toBeNull();
  });
});

describe("trendLine", () => {
  const t = { test_id: "hba1c.hba1c", direction: "rising", toward: "out_of_range", first_value: 6.1, last_value: 7, unit_c: "%", points: 3 } as const;
  it("states the movement in plain words", () => {
    expect(trendLine(t)).toBe("Rising over 3 reports, heading out of range: 6.1 to 7 %");
    expect(trendLine({ ...t, direction: "falling", toward: "critical", unit_c: "" })).toBe(
      "Falling over 3 reports, heading toward a critical value: 6.1 to 7",
    );
  });
  it("groups big numbers the Indian way", () => {
    expect(trendLine({ ...t, first_value: 150000, last_value: 245000, unit_c: "/uL" })).toContain("1,50,000 to 2,45,000 /uL");
  });
  it("reads in Hindi when asked", () => {
    expect(trendLine(t, "hi")).toMatch(/[ऀ-ॿ]/);
    expect(trendLine(t, "hi")).toContain("3");
  });
});

describe("testLabel", () => {
  it("makes a readable name from the catalogue id", () => {
    expect(testLabel("lft.alt")).toBe("ALT");
    expect(testLabel("hba1c.hba1c")).toBe("HBA1C");
    expect(testLabel("cbc.hemoglobin")).toBe("Hemoglobin");
    expect(testLabel("lipid.total_cholesterol")).toBe("Total cholesterol");
    expect(testLabel("vitamins.d")).toBe("Vitamins D");
    expect(testLabel("odd")).toBe("odd");
  });
});

describe("doctor copy", () => {
  it("gives every doctor string a Hindi line", () => {
    for (const [key, pair] of Object.entries(STRINGS)) {
      if (key.startsWith("doc")) expect(/[ऀ-ॿ]/.test(pair.hi), key).toBe(true);
    }
  });
});
