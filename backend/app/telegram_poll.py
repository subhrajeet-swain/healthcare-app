"""Telegram long-polling service: `getUpdates` -> inbound rows + `msg.inbound` jobs.

The offset lives in memory only (ruling T12): Telegram keeps unconfirmed updates for 24 h and the
inbound primary key makes a re-read after a restart a no-op. One replica, role hc_app.

    python -m app.telegram_poll
"""

from __future__ import annotations

import logging
import time
from uuid import UUID

from app import db, msg_jobs, telegram
from app.auth import _tenant_by_slug
from app.config import settings
from app.errors import ApiError

log = logging.getLogger("app.telegram_poll")

OFF_SLEEP_S = 60
MAX_BACKOFF_S = 30


def store_update(tid: UUID, update: dict) -> bool:
    """False for an ignored update (group, edit ...) or a duplicate."""
    m = telegram.parse_update(update)
    return m is not None and msg_jobs.store_inbound(tid, "telegram", m)


def poll_once(tid: UUID, offset: int | None) -> int | None:
    """One long poll. The next offset: past the last update, only after its row committed."""
    params: dict = {"timeout": telegram.POLL_TIMEOUT, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    updates = telegram.tg_call("getUpdates", params)
    for u in updates:
        store_update(tid, u)
    return max(u["update_id"] for u in updates) + 1 if updates else offset


def serve(iterations: int | None = None, sleep=time.sleep) -> None:
    """Poll forever. Errors are logged and backed off 1, 2, 4 ... 30 s, as `worker.serve` does."""
    backoff = 0
    offset: int | None = None
    warned = ""
    n = 0
    while iterations is None or n < iterations:
        n += 1
        try:
            tid, why = None, ""
            if not settings.telegram_bot_token:
                why = "telegram off: no bot token"
            else:
                try:
                    tid = _tenant_by_slug(settings.telegram_lab)
                except ApiError:
                    why = "telegram off: unknown lab slug"
            if tid is None:
                if warned != why:
                    log.warning(why)
                    warned = why
                sleep(OFF_SLEEP_S)
                continue
            warned = ""
            offset = poll_once(tid, offset)
            backoff = 0
        except Exception:  # noqa: BLE001 - nothing short of a stop signal may end the loop
            log.exception("telegram poll error; retrying")
            backoff = min(MAX_BACKOFF_S, backoff * 2 or 1)
            sleep(backoff)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    db.init_pool(settings.database_url)
    serve()


if __name__ == "__main__":
    main()
