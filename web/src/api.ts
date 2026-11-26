import type { Lang } from "./i18n";
import type { Role } from "./routes";

export type { Lang };

export type Me = {
  id: string;
  role: Role;
  phone_masked: string | null; // null for a child, who has no phone
  name: string | null;
  consent: { core: boolean; whatsapp: boolean };
};

export type Relation = "child" | "parent" | "spouse" | "other";
export type LinkStatus = "pending" | "active";
/** members: people I manage. invites: people who manage me, or ask to. */
export type Family = {
  members: { link_id: string; member_id: string; relation: Relation; status: LinkStatus; name: string | null }[];
  invites: { link_id: string; manager_id: string; relation: Relation; status: LinkStatus; name: string | null }[];
};

// The family member the signed-in patient is acting for; null is themselves. Per tab, so
// two tabs can show two people. The server checks the link on every request.
const PROFILE_KEY = "ph:profile";

export function getProfile(): string | null {
  try {
    return sessionStorage.getItem(PROFILE_KEY);
  } catch {
    return null;
  }
}

export function setProfile(id: string | null) {
  try {
    if (id) sessionStorage.setItem(PROFILE_KEY, id);
    else sessionStorage.removeItem(PROFILE_KEY);
  } catch {
    /* storage blocked: the switch holds until reload */
  }
  current = id;
}

let current = getProfile();

function profileHeader(own: boolean): Record<string, string> {
  return !own && current ? { "X-Profile": current } : {};
}

/** For URLs the browser fetches itself (EventSource, file links): they cannot send headers. */
function withProfile(path: string): string {
  return current ? `${path}?profile=${encodeURIComponent(current)}` : path;
}

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string) {
    super(code);
    this.status = status;
    this.code = code;
  }
}

/** `own`: a personal route (account, consent, family) that never takes a profile. */
async function req<T>(method: string, path: string, body?: unknown, own = false): Promise<T> {
  const r = await fetch(path, {
    method,
    credentials: "include",
    headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...profileHeader(own) },
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
  | "under_review" // a patient's report held for the lab's doctor: nothing else leaves the server
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
/** The doctor's one line on a released report, in both languages (the server writes it). */
export type DoctorNote = { option: string; text: Record<Lang, string> };
export type ReportDetail = ReportSummary & {
  failure_message: string | null;
  has_file: boolean;
  steps: Step[];
  // a report held for review (status "under_review") has none of these four: the keys are absent
  next_step?: "follow_up_package" | "doctor_consult" | "no_action" | null;
  urgent?: boolean;
  results?: Result[];
  explanations?: Partial<Record<Lang, { source: "model" | "template"; statements: Statement[] }>>;
  review_pending?: boolean; // a doctor still has to look at it (a warnings-only report shows as it is)
  doctor_note?: DoctorNote; // once a doctor edited or escalated
};
/** A report as a doctor sees it through a share link: no file, no chat, no pipeline steps. */
export type SharedReport = Omit<ReportDetail, "steps" | "has_file" | "failure_message">;
export type SharedView = { expires_at: string; reports: SharedReport[] };
export type ShareLink = { id: string; report_ids: string[]; expires_at: string; created_at: string };
export type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  tier: string;
  created_at: string;
  channel?: "web" | "whatsapp"; // absent on a message just sent from this page: it is web
};
/** The patient's WhatsApp link: `lab_number` is the number to message, null when the lab has none. */
export type WaLink = {
  available: boolean;
  lab_number: string | null;
  linked: boolean;
  number_masked: string | null;
  opted_in: boolean;
};
export type WaLinkCode = { code: string; lab_number: string; expires_in: number }; // expires_in: seconds
export type StaffReport = {
  id: string;
  status: Status;
  triage: Triage | null;
  source: "patient" | "lab";
  created_at: string;
  phone_masked: string | null;
  name: string | null;
};
export const TERMINAL: Status[] = ["ready", "needs_review", "under_review", "failed"];

/** One test across the patient's reports, in the canonical unit; a held report is never in it. */
export type TimelinePoint = {
  report_id: string;
  observed_on: string;
  value: number;
  ref_low: number | null;
  ref_high: number | null;
};
export type TimelineTest = {
  test_id: string;
  test_name: string;
  unit: string;
  points: TimelinePoint[];
  // results whose printed unit cannot be converted: listed, never drawn
  excluded: { report_id: string; observed_on: string; unit: string; reason: string }[];
  trend: {
    direction: "rising" | "falling";
    toward: "out_of_range" | "critical";
    review_status: "pending" | "approved" | "edited" | "escalated" | null;
  } | null;
};

export type ReviewKind = "report" | "trend" | "chat";
export type ReviewReason = "red" | "warnings" | "trend" | "gated_answer";
export type Decision = "approve" | "edit" | "escalate";
export type NoteOption = "repeat_test" | "see_doctor_soon" | "no_action_needed" | "call_lab";
export type Trend = {
  test_id: string;
  direction: "rising" | "falling";
  toward: "out_of_range" | "critical";
  first_value: number;
  last_value: number;
  unit_c: string;
  points: number;
};
export type ReviewItem = {
  id: string;
  kind: ReviewKind;
  reason: ReviewReason;
  status: "pending" | "approved" | "edited" | "escalated";
  note_option: NoteOption | null;
  created_at: string;
  due_at: string;
  patient_name: string | null;
  report_id: string | null;
  trend: Trend | null;
  chat: { question: string | null; reply: string | null } | null;
};
export type ReviewDetail = ReviewItem & { report: ReportDetail | null };

async function upload<T>(path: string, file: File): Promise<T> {
  const body = new FormData();
  body.append("file", file);
  const r = await fetch(path, { method: "POST", credentials: "include", body, headers: profileHeader(false) });
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
  me: () => req<Me>("GET", "/api/me", undefined, true),
  grantConsent: () => req<void>("POST", "/api/consents", { purpose: "core", version: CONSENT_VERSION }, true),
  logout: () => req<void>("POST", "/api/auth/logout", undefined, true),
  deleteMe: () => req<void>("DELETE", "/api/me", undefined, true),
  family: () => req<Family>("GET", "/api/family", undefined, true),
  addChild: (name: string) =>
    req<{ link_id: string }>("POST", "/api/family", { relation: "child", name, version: CONSENT_VERSION }, true),
  invite: (relation: Exclude<Relation, "child">, name: string, phone: string) =>
    req<{ link_id: string }>("POST", "/api/family", { relation, name, phone }, true),
  acceptInvite: (linkId: string) => req<void>("POST", `/api/family/${linkId}/accept`, undefined, true),
  revokeLink: (linkId: string) => req<void>("DELETE", `/api/family/${linkId}`, undefined, true),
  waLink: () => req<WaLink>("GET", "/api/whatsapp/link", undefined, true),
  waLinkCode: (language: Lang) => req<WaLinkCode>("POST", "/api/whatsapp/link-code", { language }, true),
  waUnlink: () => req<void>("DELETE", "/api/whatsapp/link", undefined, true),
  exportUrl: "/api/me/export",
  reports: () => req<ReportSummary[]>("GET", "/api/reports"),
  timeline: () => req<TimelineTest[]>("GET", "/api/timeline"),
  report: (id: string) => req<ReportDetail>("GET", `/api/reports/${id}`),
  uploadReport: (file: File) => upload<{ id: string; status: Status }>("/api/reports", file),
  fileUrl: (id: string) => withProfile(`/api/reports/${id}/file`),
  eventsUrl: (id: string) => withProfile(`/api/reports/${id}/events`),
  chatHistory: (id: string) => req<ChatMessage[]>("GET", `/api/reports/${id}/chat`),
  ask: (id: string, question: string, language: Lang) =>
    req<{ reply: string; tier: string }>("POST", `/api/reports/${id}/chat`, { question, language }),
  share: (reportIds: string[], hours: number) =>
    req<{ url: string; expires_at: string }>("POST", "/api/share", { report_ids: reportIds, hours }),
  shares: () => req<ShareLink[]>("GET", "/api/share"),
  unshare: (id: string) => req<void>("DELETE", `/api/share/${id}`),
  // the doctor's door: no session, so no profile header either
  shared: (slug: string, token: string) =>
    req<SharedView>("GET", `/api/share/${encodeURIComponent(slug)}/${encodeURIComponent(token)}`, undefined, true),
  staffReports: () => req<StaffReport[]>("GET", "/api/staff/reports"),
  order: (phone: string, name: string) =>
    req<{ id: string }>("POST", "/api/staff/orders", { phone, name: name || null }),
  markInLab: (id: string) => req<void>("POST", `/api/staff/reports/${id}/status`, { status: "in_lab" }),
  doctorQueue: () => req<ReviewItem[]>("GET", "/api/doctor/queue"),
  doctorReview: (id: string) => req<ReviewDetail>("GET", `/api/doctor/reviews/${id}`),
  decide: (id: string, action: Decision, option: NoteOption | null = null) =>
    req<{ status: ReviewItem["status"] }>("POST", `/api/doctor/reviews/${id}`, { action, option }),
  staffUpload: (id: string, file: File) => upload<{ status: Status }>(`/api/staff/reports/${id}/file`, file),
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
  too_many_messages: {
    en: "You've asked 30 questions about this report in the last hour. Try again later.",
    hi: "आपने पिछले एक घंटे में इस रिपोर्ट के बारे में 30 सवाल पूछे हैं। थोड़ी देर बाद फिर पूछें।",
  },
  report_not_ready: {
    en: "This report isn't ready yet. Ask again when it's explained.",
    hi: "यह रिपोर्ट अभी तैयार नहीं है। समझाए जाने के बाद फिर पूछें।",
  },
  bad_transition: {
    en: "This report has already moved on. Refresh the list.",
    hi: "यह रिपोर्ट आगे बढ़ चुकी है। सूची रीफ़्रेश करें।",
  },
  not_a_patient: {
    en: "This number belongs to lab staff, not a patient.",
    hi: "यह नंबर लैब स्टाफ़ का है, मरीज़ का नहीं।",
  },
  under_review: {
    en: "Your lab's doctor is still reviewing this report. You can ask questions once they have.",
    hi: "आपकी लैब के डॉक्टर अभी यह रिपोर्ट देख रहे हैं। उनके देख लेने के बाद आप सवाल पूछ सकते हैं।",
  },
  already_decided: {
    en: "This item was already decided, by another doctor or by the timeout. Go back to the queue.",
    hi: "यह पहले ही तय हो चुका है, किसी दूसरे डॉक्टर ने या समय-सीमा ने। सूची पर वापस जाएं।",
  },
  invalid_option: {
    en: "That note isn't one of the four allowed. Pick one again.",
    hi: "यह नोट चार मान्य नोट में से नहीं है। फिर से चुनें।",
  },
  cannot_escalate_chat: {
    en: "A chat answer can't be escalated. Approve it, or edit it with a note.",
    hi: "चैट के जवाब को आगे नहीं भेजा जा सकता। उसे मंज़ूर करें, या नोट के साथ बदलें।",
  },
  consent_required: {
    en: "Give consent on the first screen before uploading a report. For a family member, they sign in and give it themselves.",
    hi: "रिपोर्ट अपलोड करने से पहले पहली स्क्रीन पर सहमति दें। परिवार के सदस्य के लिए, वे ख़ुद साइन इन करके सहमति देते हैं।",
  },
  own_phone: {
    en: "That's your own number. Enter your family member's mobile number.",
    hi: "यह आपका अपना नंबर है। परिवार के सदस्य का मोबाइल नंबर डालें।",
  },
  already_linked: {
    en: "This person is already in your family list.",
    hi: "यह व्यक्ति पहले से आपकी परिवार सूची में है।",
  },
  whatsapp_unavailable: {
    en: "Your lab hasn't set up WhatsApp yet.",
    hi: "आपकी लैब ने अभी WhatsApp शुरू नहीं किया है।",
  },
  invalid_name: { en: "Enter a name.", hi: "नाम डालें।" },
  too_many_invites: {
    en: "Too many invites are waiting. Wait for some to be accepted, or remove them.",
    hi: "बहुत सारे न्योते इंतज़ार में हैं। कुछ के मंज़ूर होने तक रुकें, या उन्हें हटा दें।",
  },
};
const FALLBACK = {
  en: "Something went wrong on our side. Try again in a minute.",
  hi: "हमारी तरफ़ से कुछ गड़बड़ हुई। एक मिनट बाद फिर कोशिश करें।",
};

export function messageFor(e: unknown, lang: Lang = "en"): string {
  return ((e instanceof ApiError && MESSAGES[e.code]) || FALLBACK)[lang];
}
