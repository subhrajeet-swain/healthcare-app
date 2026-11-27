"""Dev tool: store a Telegram private-chat update as the poller would, with no Telegram involved.

Run from backend/ with the app role, then read the replies in `docker compose logs worker`
(log-only without a bot token; a `--pdf` needs a token, so it is for the live check only).
Needs TELEGRAM_BOT_TOKEN set (its bot id is part of the inbound id) and the tenant TELEGRAM_LAB.

    DATABASE_URL=postgresql://hc_app:app_dev@localhost:5433/healthcare \
        uv run python ../scripts/tg_fake.py --chat 1001 --text "/start <code>"
"""

import argparse
import random

p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
p.add_argument("--chat", type=int, required=True, help="private chat id")
g = p.add_mutually_exclusive_group(required=True)
g.add_argument("--text")
g.add_argument("--pdf", help="path; the file_id is its name (the real download needs a token)")
a = p.parse_args()

from app import db, telegram_poll  # noqa: E402  (after argparse so --help needs no database)
from app.auth import _tenant_by_slug  # noqa: E402
from app.config import settings  # noqa: E402

message: dict = {"chat": {"id": a.chat, "type": "private"}}
if a.text is not None:
    message["text"] = a.text
else:
    message["document"] = {"file_id": a.pdf}
db.init_pool(settings.database_url)
tid = _tenant_by_slug(settings.telegram_lab)
update = {"update_id": random.randint(1, 2**31), "message": message}
print("stored" if telegram_poll.store_update(tid, update) else "ignored")
