"""Background worker: claims jobs with SKIP LOCKED and runs the report pipeline.

Runs as hc_worker, which can see every tenant's jobs (one policy, 003) but is
tenant-scoped like hc_app everywhere else. Each job's work runs in a transaction with
SET LOCAL app.tenant_id taken from the job row, never from file contents.

    python -m app.worker
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app import db, files, reports, tracing
from app.brain.extract import ExtractionFailed
from app.brain.pipeline import PipelineDeps, PipelineResult, build_graph, run, thread_id
from app.config import settings
from app.crypto import cipher_for

log = logging.getLogger("app.worker")

STALE_AFTER = timedelta(minutes=5)
MAX_ATTEMPTS = 3
RETRY_STEP = timedelta(seconds=30)
GIVE_UP = (
    "We could not finish reading this report. Please try uploading it again, "
    "or ask your lab for help."
)


class WaitingConsent(Exception):
    """The patient has not consented yet; nothing leaves for a model until they do."""


class ReportGone(Exception):
    """The report was deleted (delete-my-data) while its job was in flight."""


def claim(conn: psycopg.Connection) -> dict | None:
    """Take one due job (or a running one whose worker died). Caller commits."""
    return conn.execute(
        """
        UPDATE jobs SET status = 'running', locked_at = now(), attempts = attempts + 1
        WHERE id = (
            SELECT id FROM jobs
            WHERE (status = 'queued' AND run_after <= now())
               OR (status = 'running' AND locked_at < now() - %s AND attempts < %s)
            ORDER BY run_after
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING *
        """,
        (STALE_AFTER, MAX_ATTEMPTS),
    ).fetchone()


def _sweep_dead() -> None:
    """Jobs whose worker died on every attempt (OOM, hang): fail them instead of looping."""
    with _tx() as c:
        dead = c.execute(
            "UPDATE jobs SET status = 'failed', locked_at = NULL "
            "WHERE status = 'running' AND locked_at < now() - %s AND attempts >= %s "
            "RETURNING tenant_id, payload",
            (STALE_AFTER, MAX_ATTEMPTS),
        ).fetchall()
    for d in dead:
        _try_status(d["tenant_id"], UUID(d["payload"]["report_id"]), "failed", GIVE_UP)


def _tx(tenant_id: UUID | None = None):
    # same helper the owner uses; here the URL is the restricted worker role
    return db.owner_tx(settings.worker_database_url, tenant_id)


def _finish_job(job_id: UUID, status: str, retry_in: timedelta | None = None) -> None:
    with _tx() as c:
        if retry_in is None:
            c.execute(
                "UPDATE jobs SET status = %s, locked_at = NULL WHERE id = %s", (status, job_id)
            )
        else:
            c.execute(
                "UPDATE jobs SET status = 'queued', locked_at = NULL, run_after = now() + %s "
                "WHERE id = %s",
                (retry_in, job_id),
            )


def _set_status(tid: UUID, rid: UUID, status: str, message: str | None = None) -> None:
    with _tx(tid) as c:
        if c.execute("SELECT 1 FROM reports WHERE id = %s", (rid,)).fetchone() is None:
            raise ReportGone
        reports.set_status(c, tid, rid, status, message)


def _save(tid: UUID, rid: UUID, res: PipelineResult) -> None:
    with _tx(tid) as c:
        if c.execute("SELECT 1 FROM reports WHERE id = %s FOR UPDATE", (rid,)).fetchone() is None:
            raise ReportGone
        reports.store_result(c, tid, rid, res)


def _saver_conn() -> psycopg.Connection:
    return psycopg.connect(
        settings.graph_database_url,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options="-c search_path=graph",
    )


def _pipeline(job: dict, models: dict | None, saver) -> None:
    tid, rid = job["tenant_id"], UUID(job["payload"]["report_id"])
    with _tx(tid) as c:
        report = c.execute("SELECT * FROM reports WHERE id = %s", (rid,)).fetchone()
        if report is None:
            raise ReportGone
        user = c.execute("SELECT * FROM users WHERE id = %s", (report["user_id"],)).fetchone()
        consented = c.execute(
            "SELECT 1 FROM consents WHERE user_id = %s AND purpose = 'core' "
            "AND withdrawn_at IS NULL",
            (user["id"],),
        ).fetchone()
        if consented is None:
            raise WaitingConsent  # a lab upload; granting consent re-queues it
        cipher = cipher_for(c, tid)
    # identifiers are only used to redact the text layer; never logged or put in graph state
    known = [cipher.decrypt(user["phone_enc"])]
    if user["name_enc"]:
        known.append(cipher.decrypt(user["name_enc"]))
    mime = report["file_mime"]

    def load_file() -> tuple[bytes, str]:
        try:
            return files.load(cipher, tid, rid), mime
        except FileNotFoundError:
            raise ReportGone from None

    models = models or {}
    deps = PipelineDeps(
        load_file=load_file,
        known=known,
        on_status=lambda s: _set_status(tid, rid, s),
        extract_model=models.get("extract"),
        explain_model=models.get("explain"),
    )
    _save(tid, rid, run(build_graph(deps, saver), thread_id(tid, rid)))


def run_once(models: dict | None = None) -> bool:
    """Process at most one job. Returns False when there was nothing to do."""
    from langgraph.checkpoint.postgres import PostgresSaver

    _sweep_dead()
    with _tx() as c:
        job = claim(c)
    if job is None:
        return False

    tid = job["tenant_id"]
    rid = UUID(job["payload"]["report_id"])
    thread = thread_id(tid, rid)
    with _saver_conn() as sc:
        saver = PostgresSaver(sc)
        ended = True
        try:
            _pipeline(job, models, saver)
            _finish_job(job["id"], "done")
        except ReportGone:
            _finish_job(job["id"], "done")
        except WaitingConsent:
            _finish_job(job["id"], "waiting_consent")
        except ExtractionFailed as e:
            # the detail can echo model output (pydantic input_value): never log it
            log.info("report %s: extraction failed (%s)", rid, type(e.__cause__).__name__)
            _try_status(tid, rid, "failed", e.message)
            _finish_job(job["id"], "done")
        except Exception:
            log.exception("report %s: attempt %s failed", rid, job["attempts"])
            if job["attempts"] >= MAX_ATTEMPTS:
                _try_status(tid, rid, "failed", GIVE_UP)
                _finish_job(job["id"], "failed")
            else:
                ended = False  # keep the checkpoint: the retry resumes from it
                _finish_job(job["id"], "queued", retry_in=RETRY_STEP * job["attempts"])
        finally:
            if ended:
                saver.delete_thread(thread)
    return True


def _try_status(tid: UUID, rid: UUID, status: str, message: str | None) -> None:
    try:
        _set_status(tid, rid, status, message)
    except ReportGone:
        pass


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    tracing.install_defaults()
    if not settings.worker_database_url or not settings.graph_database_url:
        raise SystemExit("WORKER_DATABASE_URL and GRAPH_DATABASE_URL are required")
    log.info("worker started")
    while True:
        if not run_once():
            time.sleep(1)  # ponytail: 1 s poll; LISTEN on a jobs channel if latency matters


if __name__ == "__main__":
    main()
