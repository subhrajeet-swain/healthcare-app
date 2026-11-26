import type { NoteOption, ReviewReason, Trend, Triage } from "./api";
import type { Lang, Pair } from "./i18n";
import { fmt } from "./words";

// Hindi lines are machine-drafted; a native speaker must review them before real users.

const REASON: Record<ReviewReason, Pair> = {
  red: { en: "Urgent result", hi: "तुरंत ध्यान वाला परिणाम" },
  warnings: { en: "Check the reading", hi: "रीडिंग जांचें" },
  trend: { en: "Trend", hi: "ट्रेंड" },
  gated_answer: { en: "Chat answer", hi: "चैट का जवाब" },
};

/** The word on a queue card for why the item waits. */
export function reasonWord(reason: ReviewReason, lang: Lang = "en"): string {
  return REASON[reason][lang];
}

/** The state colour that goes with that word; a chat answer has no clinical state, so none. */
export function reasonTone(reason: ReviewReason): Triage | null {
  return reason === "red" ? "red" : reason === "gated_answer" ? null : "amber";
}

/** The four fixed notes an edit may pick, as short pill labels (the server holds the full lines). */
export const NOTE_OPTIONS: NoteOption[] = ["repeat_test", "see_doctor_soon", "no_action_needed", "call_lab"];
export const NOTE: Record<NoteOption, Pair> = {
  repeat_test: { en: "Repeat the test", hi: "जांच दोबारा कराएं" },
  see_doctor_soon: { en: "See a doctor soon", hi: "जल्द डॉक्टर को दिखाएं" },
  no_action_needed: { en: "No action needed", hi: "कार्रवाई की ज़रूरत नहीं" },
  call_lab: { en: "Call the lab today", hi: "आज ही लैब को फ़ोन करें" },
};

const UNIT: Record<"min" | "h" | "d", Pair> = {
  min: { en: "min", hi: "मिनट" },
  h: { en: "h", hi: "घंटे" },
  d: { en: "d", hi: "दिन" },
};
const DUE: Record<"now" | "in" | "over", Pair> = {
  now: { en: "due now", hi: "अभी देय" },
  in: { en: "due in {n} {unit}", hi: "{n} {unit} में देय" },
  over: { en: "overdue {n} {unit}", hi: "{n} {unit} की देरी" },
};

/** "due in 2 h" or "overdue 15 min", one unit, rounded down; inside a minute either way, "due now". */
export function dueLabel(dueAt: string, now: Date, lang: Lang = "en"): string {
  const due = Date.parse(dueAt);
  if (!Number.isFinite(due)) return "";
  const diff = due - now.getTime();
  const mins = Math.floor(Math.abs(diff) / 60_000);
  if (mins < 1) return DUE.now[lang];
  const [n, unit] = mins < 60 ? [mins, "min"] : mins < 1440 ? [Math.floor(mins / 60), "h"] : [Math.floor(mins / 1440), "d"];
  return DUE[diff > 0 ? "in" : "over"][lang].replace("{n}", String(n)).replace("{unit}", UNIT[unit as "min" | "h" | "d"][lang]);
}

const DIRECTION: Record<Trend["direction"], Pair> = {
  rising: { en: "Rising", hi: "बढ़ रहा है" },
  falling: { en: "Falling", hi: "घट रहा है" },
};
const TOWARD: Record<Trend["toward"], Pair> = {
  out_of_range: { en: "heading out of range", hi: "सीमा से बाहर जा रहा है" },
  critical: { en: "heading toward a critical value", hi: "गंभीर मान की ओर बढ़ रहा है" },
};
const TREND: Pair = {
  en: "{dir} over {n} reports, {toward}: {a} to {b}{unit}",
  hi: "{n} रिपोर्ट में {dir}, {toward}: {a} से {b}{unit}",
};

/** One sentence for a trend card; the numbers are the server's, in the canonical unit. */
export function trendLine(t: Trend, lang: Lang = "en"): string {
  const vars: Record<string, string> = {
    dir: DIRECTION[t.direction][lang],
    toward: TOWARD[t.toward][lang],
    n: String(t.points),
    a: fmt(t.first_value),
    b: fmt(t.last_value),
    unit: t.unit_c ? ` ${t.unit_c}` : "",
  };
  return TREND[lang].replace(/\{(\w+)\}/g, (_, k: string) => vars[k]);
}

/** A readable name from a catalogue id ("lft.alt" is "ALT"). The queue carries ids, not names;
 * the review screen takes the real name from the report's own results. */
export function testLabel(id: string): string {
  const [group, name] = id.split(".");
  if (!name) return id;
  const word = name.replaceAll("_", " ");
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  if (word.length < 2) return `${cap(group)} ${word.toUpperCase()}`;
  return word.length <= 4 || /\d/.test(word) ? word.toUpperCase() : cap(word);
}
