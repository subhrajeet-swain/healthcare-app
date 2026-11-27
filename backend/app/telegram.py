"""Telegram adapter: parse an update, word replies, send, media.

The same surface as `whatsapp` (ruling T8), plus two module-level Bot API calls (`tg_call`,
`tg_get_bytes`) that tests replace. The bot token sits in every Bot API URL, so no error raised
here carries an httpx exception or its URL, and the httpx logger stays at WARNING (ruling T14).
"""

from __future__ import annotations

import logging
import re

import httpx

from app import files
from app.config import settings
from app.errors import ApiError
from app.whatsapp import Inbound

log = logging.getLogger("app.telegram")
logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx logs each URL, token included, at INFO

API = "https://api.telegram.org"
CHUNK = 4096
POLL_TIMEOUT = 30
TIMEOUT = 40


class TelegramError(Exception):
    """A Bot API call failed. The message names the method and status, never the URL."""


# Hindi lines are machine-drafted; a native speaker must review them before real users.
# No numbers, no medical claims; `{lab}` is the only placeholder.
COPY: dict[str, dict[str, str]] = {
    "linked": {
        "en": "This Telegram chat is now linked to your account. "
        "Send /report to get your latest report, or /stop to stop messages.",
        "hi": "यह Telegram चैट अब आपके खाते से जुड़ गई है। "
        "अपनी ताज़ा रिपोर्ट पाने के लिए /report भेजें, या संदेश बंद करने के लिए /stop भेजें।",
    },
    "link_from_app": {
        "en": "To link this chat, open the app, choose Telegram, and tap the link it shows.",
        "hi": "इस चैट को जोड़ने के लिए ऐप खोलें, Telegram चुनें, और वहां दिखे लिंक पर टैप करें।",
    },
    "bad_code": {
        "en": "That link did not work. It may have expired. "
        "Please get a new link in the app and try again.",
        "hi": "यह लिंक काम नहीं किया। हो सकता है उसकी समय-सीमा खत्म हो गई हो। "
        "कृपया ऐप में नया लिंक लें और फिर कोशिश करें।",
    },
    "stopped": {
        "en": "You will not get any more messages from us on Telegram. "
        "Send /start to turn them back on.",
        "hi": "अब हम आपको Telegram पर कोई संदेश नहीं भेजेंगे। दोबारा चालू करने के लिए /start भेजें।",
    },
    "started": {
        "en": "Telegram messages are on again. Send /report to get your latest report.",
        "hi": "Telegram संदेश फिर से चालू हो गए हैं। अपनी ताज़ा रिपोर्ट के लिए /report भेजें।",
    },
    "consent_needed": {
        "en": "We need your consent before we can help you on Telegram. "
        "Please open the app and give it first.",
        "hi": "Telegram पर मदद करने से पहले हमें आपकी सहमति चाहिए। "
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
        "en": "Write any question about your report here, or send /report to read it again.",
        "hi": "अपनी रिपोर्ट के बारे में कोई सवाल यहां लिखें, या दोबारा पढ़ने के लिए /report भेजें।",
    },
    "review_complete": {
        "en": "A doctor at {lab} has reviewed your report. "
        "Send /report to read it, or open the app.",
        "hi": "{lab} के एक डॉक्टर ने आपकी रिपोर्ट देख ली है। "
        "पढ़ने के लिए /report भेजें, या ऐप खोलें।",
    },
    "trend_alert": {
        "en": "There is a new trend in your results at {lab}. Please open the app to see it.",
        "hi": "{lab} में आपके परिणामों में एक नया रुझान दिखा है। कृपया देखने के लिए ऐप खोलें।",
    },
}


def bot_id() -> str:
    """The token's part before `:`; not secret (ruling T13)."""
    return settings.telegram_bot_token.split(":", 1)[0]


def parse_update(update: dict) -> Inbound | None:
    """A new message in a private chat, or None (groups, channels, edits, other update types)."""
    try:
        m = update["message"]
        if m["chat"]["type"] != "private":
            return None
        base = (f"tg:{bot_id()}:{int(update['update_id'])}", "", str(m["chat"]["id"]))
        if isinstance(m.get("text"), str):
            return Inbound(*base, "text", text=m["text"])
        if m.get("document"):
            return Inbound(*base, "media", media_id=str(m["document"]["file_id"]))
        if m.get("photo"):  # sizes ascending: the last is the largest
            return Inbound(*base, "media", media_id=str(m["photo"][-1]["file_id"]))
        return Inbound(*base, "other")
    except (AttributeError, KeyError, TypeError, ValueError, IndexError):
        return None


_START = re.compile(r"/start(?:\s+([A-Za-z0-9_-]{1,64}))?", re.IGNORECASE)


def command(text: str) -> tuple[str, str | None] | None:
    """`/start <code>`, `/start`, `/stop` or `/report` (any case); None means a question."""
    text = text.strip()
    if m := _START.fullmatch(text):
        return ("link", m[1]) if m[1] else ("start", None)  # the code keeps its case
    word = text.lower()
    return (word[1:], None) if word in ("/stop", "/report") else None


def send_text(account: str, to: str, text: str) -> None:
    """Deliver one message (`account` is unused: one bot); with no token only log it."""
    if not settings.telegram_bot_token:
        if settings.env == "prod":
            log.info("telegram send skipped: no bot token")
        else:
            log.info("telegram send skipped: to=%s %s", to, text)
        return
    tg_call("sendMessage", {"chat_id": to, "text": text})


_BAD_PATH = re.compile(r"\.\.|//|:")


def fetch_media(file_id: str) -> bytes:
    """Download a file a chat sent. The caller then runs `files.check_bytes` on it (ruling T15)."""
    meta = tg_call("getFile", {"file_id": file_id})
    if int(meta.get("file_size") or 0) > files.MAX_BYTES:
        raise ApiError(413, "file_too_large")
    path = str(meta.get("file_path") or "")
    if not path or path.startswith("/") or _BAD_PATH.search(path):
        raise ApiError(415, "unsupported_file")  # only api.telegram.org/file/... is ever fetched
    return tg_get_bytes(path)


def _status(e: httpx.HTTPError) -> str:
    return str(e.response.status_code) if isinstance(e, httpx.HTTPStatusError) else type(e).__name__


def tg_call(method: str, params: dict) -> dict:
    """POST a Bot API method; its `result`. Any failure is a TelegramError without the URL."""
    url = f"{API}/bot{settings.telegram_bot_token}/{method}"
    try:
        r = httpx.post(url, json=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        raise TelegramError(f"{method} failed: {_status(e)}") from None
    except ValueError:
        raise TelegramError(f"{method} failed: bad json") from None
    if not data.get("ok"):
        raise TelegramError(f"{method} failed: {data.get('error_code')}")
    return data["result"]


def tg_get_bytes(file_path: str) -> bytes:
    """At most `MAX_BYTES + 1` bytes, so an oversize file is caught without reading all of it."""
    buf = bytearray()
    try:
        with httpx.stream(
            "GET", f"{API}/file/bot{settings.telegram_bot_token}/{file_path}", timeout=TIMEOUT
        ) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes():
                buf += chunk
                if len(buf) > files.MAX_BYTES:
                    break
    except httpx.HTTPError as e:
        raise TelegramError(f"file download failed: {_status(e)}") from None
    return bytes(buf[: files.MAX_BYTES + 1])
