import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from app import (
    auth,
    chat_api,
    db,
    doctor,
    errors,
    family,
    privacy,
    reports,
    share,
    staff,
    timeline,
    tracing,
)
from app.config import settings

# App logs (incl. the dev OTP) go to the console; uvicorn only configures its own loggers.
_log = logging.getLogger("app")
if not _log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _log.addHandler(_h)
_log.setLevel(logging.INFO)
tracing.install_defaults()


class RedactShareTokens(logging.Filter):
    """A share token in an access log would open a patient's reports to anyone reading logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) > 2 and isinstance(args[2], str):
            parts = args[2].split("/")
            if parts[1:3] == ["api", "share"] and len(parts) > 4:
                record.args = (*args[:2], "/".join(parts[:4]) + "/[token]", *args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(RedactShareTokens())


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_pool(settings.database_url)
    yield
    db.close_pool()


app = FastAPI(title="healthcare-app", lifespan=lifespan)
errors.install(app)
app.include_router(auth.router)
app.include_router(privacy.router)
app.include_router(reports.router)
app.include_router(staff.router)
app.include_router(chat_api.router)
app.include_router(doctor.router)
app.include_router(timeline.router)
app.include_router(family.router)
app.include_router(share.router)


# One serial worker: a bulk upload (10 reports at ~30-90 s) can queue for minutes with
# nothing wrong. 15 min is past any honest backlog and 3 stale windows of a hung job.
# ponytail: a worker heartbeat would tell "busy" from "stuck" exactly, add with >1 worker.
STALLED_AFTER_S = 15 * 60


@app.get("/health")
def health(response: Response) -> dict:
    """Up, and the queue is moving. A job waiting over 15 min means the worker is stuck."""
    with db.pool().connection() as c:
        q = c.execute("SELECT * FROM queue_stats()").fetchone()
    stalled = q["oldest_wait_s"] > STALLED_AFTER_S
    if stalled:
        response.status_code = 503
    return {"status": "stalled" if stalled else "ok", **q}
