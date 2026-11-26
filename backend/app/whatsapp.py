"""WhatsApp adapter: parse the webhook, check its signature, split and word replies, send, media.

Pure functions plus three module-level Graph API calls (`graph_post`, `graph_get_json`,
`graph_get_bytes`) that tests replace. Nothing here touches the database or decides anything
clinical: the caller picks what to send, this module only shapes and delivers it.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Literal

import httpx

from app import files
from app.brain.models import NextStep
from app.brain.nextstep import URGENT_EN, URGENT_HI, closing_message, urgent_message
from app.config import settings
from app.crypto import normalise_phone
from app.errors import ApiError

log = logging.getLogger("app.whatsapp")

CHUNK = 700
MEDIA_PREFIX = "https://lookaside.fbsbx.com/"
TIMEOUT = 20


# Hindi lines are machine-drafted; a native speaker must review them before real users.
# Free-text replies, sent inside the 24 hour window. No numbers, no medical claims.
COPY: dict[str, dict[str, str]] = {
    "linked": {
        "en": "Your WhatsApp number is now linked to your account. "
        "Send REPORT to get your latest report, or STOP to stop messages.",
        "hi": "आपका WhatsApp नंबर अब आपके खाते से जुड़ गया है। "
        "अपनी ताज़ा रिपोर्ट पाने के लिए REPORT भेजें, या संदेश बंद करने के लिए STOP भेजें।",
    },
    "link_from_app": {
        "en": "To link this number, open the app, choose WhatsApp, and send the code it shows "
        "here like this: LINK followed by the code.",
        "hi": "इस नंबर को जोड़ने के लिए ऐप खोलें, WhatsApp चुनें, और वहां दिखा कोड यहां इस तरह भेजें: "
        "LINK और उसके बाद कोड।",
    },
    "bad_code": {
        "en": "That code did not work. It may have expired. "
        "Please get a new code in the app and try again.",
        "hi": "यह कोड काम नहीं किया। हो सकता है उसकी समय-सीमा खत्म हो गई हो। "
        "कृपया ऐप में नया कोड लें और फिर कोशिश करें।",
    },
    "stopped": {
        "en": "You will not get any more messages from us on WhatsApp. "
        "Send START to turn them back on.",
        "hi": "अब हम आपको WhatsApp पर कोई संदेश नहीं भेजेंगे। दोबारा चालू करने के लिए START भेजें।",
    },
    "started": {
        "en": "WhatsApp messages are on again. Send REPORT to get your latest report.",
        "hi": "WhatsApp संदेश फिर से चालू हो गए हैं। अपनी ताज़ा रिपोर्ट के लिए REPORT भेजें।",
    },
    "consent_needed": {
        "en": "We need your consent before we can help you on WhatsApp. "
        "Please open the app and give it first.",
        "hi": "WhatsApp पर मदद करने से पहले हमें आपकी सहमति चाहिए। "
        "कृपया पहले ऐप खोलकर सहमति दें।",
    },
    "no_report": {
        "en": "You do not have a report yet. Upload one in the app, or send a photo or PDF "
        "of it here.",
        "hi": "आपकी कोई रिपोर्ट अभी नहीं है। ऐप में रिपोर्ट अपलोड करें, "
        "या उसका फ़ोटो या PDF यहां भेजें।",
    },
    "reading": {
        "en": "Thanks, we are reading your report. We will message you when it is ready.",
        "hi": "धन्यवाद, हम आपकी रिपोर्ट पढ़ रहे हैं। तैयार होने पर हम आपको संदेश भेजेंगे।",
    },
    "bad_file": {
        "en": "We could not read that file. "
        "Please send a clear PDF, JPEG or PNG of your lab report.",
        "hi": "हम यह फ़ाइल नहीं पढ़ सके। "
        "कृपया अपनी लैब रिपोर्ट की साफ़ PDF, JPEG या PNG फ़ाइल भेजें।",
    },
    "not_ready": {
        "en": "Your report is not ready yet. We will message you when it is.",
        "hi": "आपकी रिपोर्ट अभी तैयार नहीं है। तैयार होने पर हम आपको संदेश भेजेंगे।",
    },
    "too_many": {
        "en": "You have sent many messages in a short time. Please wait a while and try again.",
        "hi": "आपने थोड़े समय में बहुत संदेश भेजे हैं। कृपया कुछ देर रुककर फिर कोशिश करें।",
    },
    "ask_more": {
        "en": "Write any question about your report here, or send REPORT to read it again.",
        "hi": "अपनी रिपोर्ट के बारे में कोई सवाल यहां लिखें, या दोबारा पढ़ने के लिए REPORT भेजें।",
    },
}

# Pre-approved Meta templates, for sending outside the 24 hour window. The only placeholder is
# `{lab}`: a result value never goes into a template.
TEMPLATES: dict[str, dict[str, str]] = {
    "report_ready": {
        "en": "Your report from {lab} is ready. Reply REPORT to read it, or open the app.",
        "hi": "{lab} से आपकी रिपोर्ट तैयार है। पढ़ने के लिए REPORT लिखकर भेजें, या ऐप खोलें।",
    },
    "trend_alert": {
        "en": "There is a new trend in your results at {lab}. Please open the app to see it.",
        "hi": "{lab} में आपके परिणामों में एक नया रुझान दिखा है। कृपया देखने के लिए ऐप खोलें।",
    },
    "review_complete": {
        "en": "A doctor at {lab} has reviewed your report. Please open the app to read it.",
        "hi": "{lab} के एक डॉक्टर ने आपकी रिपोर्ट देख ली है। कृपया पढ़ने के लिए ऐप खोलें।",
    },
    "report_ready_red": {
        "en": "Your report from {lab} is ready and needs a doctor's attention. "
        "Please open the app or call your lab.",
        "hi": "{lab} से आपकी रिपोर्ट तैयार है और उस पर डॉक्टर का ध्यान ज़रूरी है। "
        "कृपया ऐप खोलें या अपनी लैब को फ़ोन करें।",
    },
}


@dataclass(frozen=True)
class Inbound:
    message_id: str
    phone_number_id: str
    sender: str  # E.164
    kind: Literal["text", "media", "other"]
    text: str | None = None
    media_id: str | None = None


@dataclass(frozen=True)
class Outbound:
    phone_number_id: str
    to: str
    text: str | None = None
    template: str | None = None
    lang: str = "en"
    lab: str = ""


def verify_signature(body: bytes, header: str | None, secret: str) -> bool:
    """Meta signs the raw body: `X-Hub-Signature-256: sha256=<hex HMAC-SHA256, app secret key>`."""
    if not header or not secret:
        return False
    want = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want.encode(), header.encode())  # bytes: str raises on non-ASCII


def parse(payload: dict) -> list[Inbound]:
    """Every message in a webhook payload. Never raises: a malformed shape ends the walk early."""
    out: list[Inbound] = []
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})  # `statuses` (delivery receipts) are never read
                for m in value.get("messages", []):
                    try:
                        sender = normalise_phone("+" + m["from"])
                    except ValueError:
                        continue
                    kind = m["type"]
                    base = (str(m["id"]), str(value["metadata"]["phone_number_id"]), sender)
                    if kind == "text":
                        out.append(Inbound(*base, "text", text=m["text"]["body"]))
                    elif kind in ("document", "image"):
                        out.append(Inbound(*base, "media", media_id=str(m[kind]["id"])))
                    else:
                        out.append(Inbound(*base, "other"))
    except (AttributeError, KeyError, TypeError):
        pass
    return out


def _cut(paragraph: str, limit: int):
    """Pieces of at most `limit`, cut at the last space; a run with no space is cut hard."""
    while len(paragraph) > limit:
        i = paragraph.rfind(" ", 0, limit + 1)
        i = i if i > 0 else limit
        yield paragraph[:i]
        paragraph = paragraph[i:].lstrip(" ")
    if paragraph:
        yield paragraph


def split(paragraphs: list[str], limit: int = CHUNK) -> list[str]:
    """Pack paragraphs, joined by a blank line, into messages of at most `limit` characters."""
    chunks: list[str] = []
    cur = ""
    for piece in (p for para in paragraphs for p in _cut(para, limit)):
        if cur and len(cur) + 2 + len(piece) <= limit:
            cur += "\n\n" + piece
        else:
            if cur:
                chunks.append(cur)
            cur = piece
    if cur:
        chunks.append(cur)
    return chunks


def report_paragraphs(detail: dict, lang: str) -> list[str]:
    """What a report says: explanation, doctor's note, closing line, in that order.

    A red report starts with the urgent line, exactly once (ruling T2): the pipeline stores it
    as statement 0, and it is added here only when missing (no explanation in `lang` or `en`).
    """
    expl = detail["explanations"].get(lang) or detail["explanations"].get("en") or {}
    stmts = expl.get("statements", [])
    line = closing_message(NextStep(detail["next_step"]), lang) if detail.get("next_step") else None
    if line and stmts and stmts[-1].get("source") == "system":
        stmts = stmts[:-1]  # the pipeline stores the closing line last; it is sent once, below
    out = [s["text"] for s in stmts]
    if detail.get("triage") == "red":  # an English fallback carries the English line
        out = [urgent_message(lang)] + [t for t in out if t not in (URGENT_EN, URGENT_HI)]
    if note := detail.get("doctor_note"):
        out.append(note["text"].get(lang) or note["text"]["en"])
    if line:
        out.append(line)
    return out


def send(o: Outbound) -> None:
    """Deliver one message; with no access token (dev, tests) only log it."""
    if not settings.wa_access_token:
        if settings.env == "prod":
            log.info("whatsapp send skipped: no access token")
        else:
            log.info("whatsapp send skipped: to=%s %s", o.to, o.text or f"template={o.template}")
        return
    body: dict = {"messaging_product": "whatsapp", "to": o.to}
    if o.template:
        body |= {
            "type": "template",
            "template": {
                "name": o.template,
                "language": {"code": o.lang},
                "components": [{"type": "body", "parameters": [{"type": "text", "text": o.lab}]}],
            },
        }
    else:
        body |= {"type": "text", "text": {"body": o.text}}
    graph_post(f"/{o.phone_number_id}/messages", body)


def fetch_media(media_id: str) -> bytes:
    """Download a media item Meta announced. The caller then runs `files.check_bytes` on it."""
    meta = graph_get_json(f"/{media_id}")
    if int(meta.get("file_size") or 0) > files.MAX_BYTES:
        raise ApiError(413, "file_too_large")
    url = str(meta.get("url", ""))
    if not url.startswith(MEDIA_PREFIX):  # the token goes only to Meta's media host
        raise ApiError(415, "unsupported_file")
    return graph_get_bytes(url)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.wa_access_token}"}


def graph_post(path: str, body: dict) -> dict:
    r = httpx.post(settings.wa_graph_url + path, json=body, headers=_auth(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def graph_get_json(path: str) -> dict:
    r = httpx.get(settings.wa_graph_url + path, headers=_auth(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def graph_get_bytes(url: str) -> bytes:
    """At most `MAX_BYTES + 1` bytes, so an oversize file is caught without reading all of it.

    Redirects are not followed (httpx default): the bearer token must not leave Meta's host.
    """
    buf = bytearray()
    with httpx.stream("GET", url, headers=_auth(), timeout=TIMEOUT) as r:
        r.raise_for_status()
        for chunk in r.iter_bytes():
            buf += chunk
            if len(buf) > files.MAX_BYTES:
                break
    return bytes(buf[: files.MAX_BYTES + 1])
