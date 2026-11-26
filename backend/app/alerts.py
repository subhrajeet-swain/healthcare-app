"""Doctor alert mail. It carries no patient data: one line and the queue link."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from urllib.parse import unquote, urlsplit

from app.config import settings

log = logging.getLogger("app.alerts")


def send_review_alert(to: str, link: str) -> None:
    if not settings.smtp_url:
        log.info("SMTP_URL not set; review alert not sent (queue: %s)", link)
        return
    u = urlsplit(settings.smtp_url)
    user = unquote(u.username or "")
    msg = EmailMessage()
    msg["Subject"] = "A report needs review"
    msg["From"] = user or "noreply@localhost"
    msg["To"] = to
    msg.set_content(f"A report needs review.\n\nOpen the review queue: {link}\n")
    smtp = smtplib.SMTP_SSL if u.scheme == "smtps" else smtplib.SMTP
    with smtp(u.hostname, u.port or (465 if u.scheme == "smtps" else 587), timeout=30) as s:
        if u.scheme != "smtps":
            s.starttls()
        if user:
            s.login(user, unquote(u.password or ""))
        s.send_message(msg)
