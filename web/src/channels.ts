/** `tel:` link for a lab phone: digits and a leading + only; null when there is nothing to call. */
export function telHref(phone?: string | null): string | null {
  const n = (phone ?? "").replace(/(?!^\+)\D/g, "");
  return n ? `tel:${n}` : null;
}

/** The i18n key of the "via ..." tag on a chat message; web needs none. */
export function viaKey(channel?: string): "viaWhatsApp" | "viaTelegram" | null {
  return channel === "whatsapp" ? "viaWhatsApp" : channel === "telegram" ? "viaTelegram" : null;
}
