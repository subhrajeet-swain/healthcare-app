import type { Role } from "./routes";

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
};

const MESSAGES: Record<string, string> = {
  invalid_phone: "That doesn't look like an Indian mobile number. Check the 10 digits and try again.",
  invalid_code: "That code didn't work. Check it, or ask for a new one.",
  too_many_requests: "Too many codes requested. Wait 10 minutes, then try again.",
  not_found: "We couldn't find this lab. Use the sign-in link your lab sent you.",
  unauthenticated: "You're signed out. Sign in again.",
};

export function messageFor(e: unknown): string {
  return (e instanceof ApiError && MESSAGES[e.code]) || "Something went wrong on our side. Try again in a minute.";
}
