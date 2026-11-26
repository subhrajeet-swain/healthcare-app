import type { Flag, ReportDetail, Status, Triage } from "./api";
import type { Lang, Pair } from "./i18n";

// Hindi lines are machine-drafted; a native speaker must review them before real users.

export const STATUS: Record<Status, Pair> = {
  sample_collected: { en: "Sample collected", hi: "सैंपल लिया गया" },
  in_lab: { en: "In the lab", hi: "लैब में जांच" },
  received: { en: "Report received", hi: "रिपोर्ट मिली" },
  extracting: { en: "Reading the report", hi: "रिपोर्ट पढ़ी जा रही है" },
  explaining: { en: "Writing your explanation", hi: "आसान भाषा में लिखा जा रहा है" },
  under_review: { en: "Under review", hi: "डॉक्टर देख रहे हैं" },
  ready: { en: "Ready", hi: "तैयार" },
  needs_review: { en: "Ready", hi: "तैयार" },
  failed: { en: "Could not read", hi: "पढ़ा नहीं जा सका" },
};

// The word carries the state; colour only reinforces it (Word-State Rule).
export const FLAG: Record<Flag, Pair> = {
  low: { en: "Low", hi: "कम" },
  high: { en: "High", hi: "ज़्यादा" },
  normal: { en: "Normal", hi: "सामान्य" },
  critical: { en: "Urgent", hi: "तुरंत" },
};

export const TRIAGE: Record<Triage, Pair> = {
  red: { en: "Urgent", hi: "तुरंत ध्यान दें" },
  amber: { en: "Outside range", hi: "सीमा से बाहर" },
  green: { en: "All normal", hi: "सब सामान्य" },
};

export const NEXT: Record<NonNullable<ReportDetail["next_step"]>, Pair> = {
  doctor_consult: { en: "Take these results to a doctor", hi: "इन परिणामों को डॉक्टर को दिखाएं" },
  follow_up_package: {
    en: "Ask your lab or doctor about a follow-up test",
    hi: "अपनी लैब या डॉक्टर से दोबारा जांच के बारे में पूछें",
  },
  no_action: { en: "Nothing to do now", hi: "अभी कुछ करने की ज़रूरत नहीं" },
};

const NUM = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 3 });

/** Indian digit grouping (2,45,000), in both languages: what Indian lab reports print. */
export function fmt(n: number): string {
  return NUM.format(n);
}

export function shortDate(iso: string | null, lang: Lang = "en"): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(lang === "hi" ? "hi-IN" : "en-IN", { day: "numeric", month: "short", year: "numeric" });
}
