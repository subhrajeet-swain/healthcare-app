import type { Lang } from "./i18n";
import type { Role } from "./routes";

export type { Lang };

export type Me = {
  id: string;
  role: Role;
  phone_masked: string;
  name: string | null;
  consent: { core: boolean };
};

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string) {
    super(code);
    this.status = status;
    this.code = code;
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new ApiError(r.status, typeof data.error === "string" ? data.error : "request_failed");
  }
  return (r.status === 204 ? undefined : await r.json()) as T;
}

export type Status =
  | "sample_collected"
  | "in_lab"
  | "received"
  | "extracting"
  | "explaining"
  | "needs_review"
  | "ready"
  | "failed";
export type Triage = "red" | "amber" | "green";
export type Flag = "low" | "normal" | "high" | "critical";

export type ReportSummary = {
  id: string;
  status: Status;
  triage: Triage | null;
  source: "patient" | "lab";
  created_at: string;
  collected_on: string | null;
  tests: string | null;
};
export type Step = { status: Status; at: string };
export type Result = {
  test_id: string;
  test_name: string;
  value: number;
  unit: string;
  ref_low: number | null;
  ref_high: number | null;
  flag: Flag;
  triage: Triage;
};
export type Statement = { text: string; test_ids: string[]; source: "model" | "system" };
export type ReportDetail = ReportSummary & {
  next_step: "follow_up_package" | "doctor_consult" | "no_action" | null;
  urgent: boolean;
  failure_message: string | null;
  has_file: boolean;
  steps: Step[];
  results: Result[];
  explanations: Partial<Record<Lang, { source: "model" | "template"; statements: Statement[] }>>;
};
export const TERMINAL: Status[] = ["ready", "needs_review", "failed"];

async function upload<T>(path: string, file: File): Promise<T> {
  const body = new FormData();
  body.append("file", file);
  const r = await fetch(path, { method: "POST", credentials: "include", body });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new ApiError(r.status, typeof data.error === "string" ? data.error : "request_failed");
  }
  return (await r.json()) as T;
}

export const CONSENT_VERSION = "2026-11-v1";

export const api = {
  requestOtp: (slug: string, phone: string) => req<void>("POST", `/api/auth/${slug}/otp`, { phone }),
  verify: (slug: string, phone: string, code: string) =>
    req<{ role: Role }>("POST", `/api/auth/${slug}/verify`, { phone, code }),
  me: () => req<Me>("GET", "/api/me"),
  grantConsent: () => req<void>("POST", "/api/consents", { purpose: "core", version: CONSENT_VERSION }),
  logout: () => req<void>("POST", "/api/auth/logout"),
  deleteMe: () => req<void>("DELETE", "/api/me"),
  exportUrl: "/api/me/export",
  reports: () => req<ReportSummary[]>("GET", "/api/reports"),
  report: (id: string) => req<ReportDetail>("GET", `/api/reports/${id}`),
  uploadReport: (file: File) => upload<{ id: string; status: Status }>("/api/reports", file),
  fileUrl: (id: string) => `/api/reports/${id}/file`,
  eventsUrl: (id: string) => `/api/reports/${id}/events`,
};

// Hindi lines are machine-drafted; a native speaker must review them before real users.
const MESSAGES: Record<string, { en: string; hi: string }> = {
  invalid_phone: {
    en: "That doesn't look like an Indian mobile number. Check the 10 digits and try again.",
    hi: "यह भारतीय मोबाइल नंबर नहीं लगता। 10 अंक जांचें और फिर कोशिश करें।",
  },
  invalid_code: {
    en: "That code didn't work. Check it, or ask for a new one.",
    hi: "यह कोड काम नहीं किया। इसे जांचें, या नया कोड मंगाएं।",
  },
  too_many_requests: {
    en: "Too many codes requested. Wait 10 minutes, then try again.",
    hi: "बहुत सारे कोड मंगाए गए। 10 मिनट रुकें, फिर कोशिश करें।",
  },
  not_found: {
    en: "We couldn't find this lab. Use the sign-in link your lab sent you.",
    hi: "यह लैब नहीं मिली। अपनी लैब का भेजा साइन-इन लिंक इस्तेमाल करें।",
  },
  unauthenticated: { en: "You're signed out. Sign in again.", hi: "आप साइन आउट हो गए हैं। फिर से साइन इन करें।" },
  file_too_large: {
    en: "This file is over 10 MB. Upload a smaller PDF, or a photo of each page.",
    hi: "यह फ़ाइल 10 MB से बड़ी है। छोटी PDF, या हर पेज की फ़ोटो अपलोड करें।",
  },
  unsupported_file: {
    en: "Upload a PDF, JPG or PNG file of your lab report.",
    hi: "अपनी लैब रिपोर्ट की PDF, JPG या PNG फ़ाइल अपलोड करें।",
  },
  unreadable_file: {
    en: "We couldn't open this PDF. It may be password-protected or longer than 20 pages.",
    hi: "यह PDF खुल नहीं सकी। शायद इस पर पासवर्ड है या यह 20 पेज से लंबी है।",
  },
  consent_required: {
    en: "Give consent on the first screen before uploading a report.",
    hi: "रिपोर्ट अपलोड करने से पहले पहली स्क्रीन पर सहमति दें।",
  },
};
const FALLBACK = {
  en: "Something went wrong on our side. Try again in a minute.",
  hi: "हमारी तरफ़ से कुछ गड़बड़ हुई। एक मिनट बाद फिर कोशिश करें।",
};

export function messageFor(e: unknown, lang: Lang = "en"): string {
  return ((e instanceof ApiError && MESSAGES[e.code]) || FALLBACK)[lang];
}
