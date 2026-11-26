"""Background worker: claims jobs with SKIP LOCKED and runs them by kind (`HANDLERS`).

`report.pipeline` runs the report graph; a red or warnings report parks its thread at
`review` for a doctor. `report.resume` (a doctor decided) and `review.timeout` (nobody did)
resume it; `alert.email` tells the lab's doctor inbox.

Runs as hc_worker, which can see every tenant's jobs (one policy, 003) but is
tenant-scoped like hc_app everywhere else. Each job's work runs in a transaction with
SET LOCAL app.tenant_id taken from the job row, never from file contents.

    python -m app.worker
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app import alerts, db, files, reports, review, tracing
from app.brain.extract import ExtractionFailed
from app.brain.pipeline import (
    Decision,
    PipelineDeps,
    PipelineResult,
    build_graph,
    resume,
    run,
    thread_id,
)
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


class Parked(Exception):
    """The run waits at `review` for a doctor: results saved, the thread must stay."""


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
        if "report_id" in d["payload"]:  # report.pipeline; other kinds have no report to fail
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
        report = c.execute(
            "SELECT user_id FROM reports WHERE id = %s FOR UPDATE", (rid,)
        ).fetchone()
        if report is None:
            raise ReportGone
        reports.store_result(c, tid, rid, res)
        if res.pending:
            review.open_review(
                c, tid, kind="report", reason="red" if res.triage == "red" else "warnings",
                user_id=report["user_id"], report_id=rid, thread_id=thread_id(tid, rid),
            )
    if res.pending:
        raise Parked


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


def _no_file() -> tuple[bytes, str]:
    raise AssertionError("a resume runs only `review`; it never reads the file")


# a resume runs only the `review` node: no file, no identifiers, no model
_RESUME_DEPS = PipelineDeps(load_file=_no_file, known=[], on_status=lambda s: None)
ACTIONS = {"approved": "approve", "edited": "edit", "escalated": "escalate"}


def _review_job(job: dict, saver, timeout: bool) -> None:
    """Resume a parked thread with the item's decision; a timeout first escalates a pending item.

    The item stays locked (FOR UPDATE) until the result is stored, so a doctor's decision
    and the timeout never both resume one thread (Review Focus 2). An item that is gone
    (delete-my-data), undecided (resume) or already decided (timeout), or whose thread is
    gone, ends the job without a resume.
    """
    tid = job["tenant_id"]
    graph = build_graph(_RESUME_DEPS, saver)
    with _tx(tid) as c:
        item = c.execute(
            "SELECT * FROM review_items WHERE id = %s AND kind = 'report' FOR UPDATE",
            (job["payload"]["review_item_id"],),
        ).fetchone()
        if item is None or (item["status"] == "pending") != timeout:
            return
        thread = item["thread_id"]
        if not graph.get_state({"configurable": {"thread_id": thread}}).values:
            log.warning("review item %s: thread is gone", item["id"])
            return
        if timeout:
            item = c.execute(
                "UPDATE review_items SET status = 'escalated', decided_at = now(), "
                "decided_by = NULL WHERE id = %s RETURNING *",
                (item["id"],),
            ).fetchone()
        action = ACTIONS[item["status"]]
        decision: Decision = {
            "action": action,
            "option": item["note_option"] if action == "edit" else None,
            "by": str(item["decided_by"]) if item["decided_by"] else None,
        }
        reports.store_result(c, tid, item["report_id"], resume(graph, thread, decision))
        if action == "escalate":
            review.queue_job(c, tid, "alert.email", item["id"])
    saver.delete_thread(thread)  # after commit: a failed save keeps the thread for the retry


def _alert(job: dict, models: dict | None, saver) -> None:
    with _tx(job["tenant_id"]) as c:
        item = c.execute(
            "SELECT 1 FROM review_items WHERE id = %s", (job["payload"]["review_item_id"],)
        ).fetchone()
        to = db.tenant_setting(c, "doctor_email", None)
    if item is not None and to:  # no doctor_email: the in-app queue is the only signal
        alerts.send_review_alert(to, settings.app_base_url)


HANDLERS: dict[str, Callable[[dict, dict | None, Any], None]] = {
    "report.pipeline": _pipeline,
    "report.resume": lambda job, models, saver: _review_job(job, saver, timeout=False),
    "review.timeout": lambda job, models, saver: _review_job(job, saver, timeout=True),
    "alert.email": _alert,
}


def run_once(models: dict | None = None) -> bool:
    """Process at most one job. Returns False when there was nothing to do."""
    from langgraph.checkpoint.postgres import PostgresSaver

    _sweep_dead()
    with _tx() as c:
        job = claim(c)
    if job is None:
        return False

    handler = HANDLERS.get(job["kind"])
    if handler is None:
        log.error("job %s: unknown kind %r; failed", job["id"], job["kind"])
        _finish_job(job["id"], "failed")
        return True
    tid = job["tenant_id"]
    # report.pipeline's thread is cleaned up here; the review jobs delete their own
    rid = UUID(job["payload"]["report_id"]) if "report_id" in job["payload"] else None
    thread = thread_id(tid, rid) if rid else None
    try:
        sc = _saver_conn()
    except Exception:
        _release(job["id"])  # infra down before the pipeline began: not this report's fault
        raise
    with sc:
        saver = PostgresSaver(sc)
        ended = True
        try:
            handler(job, models, saver)
            _finish_job(job["id"], "done")
        except Parked:
            ended = False  # the thread waits for a doctor; resume or timeout deletes it
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
            log.exception("job %s (%s): attempt %s failed", job["id"], job["kind"],
                          job["attempts"])
            if job["attempts"] >= MAX_ATTEMPTS:
                if rid:
                    _try_status(tid, rid, "failed", GIVE_UP)
                _finish_job(job["id"], "failed")
            else:
                ended = False  # keep the checkpoint: the retry resumes from it
                _finish_job(job["id"], "queued", retry_in=RETRY_STEP * job["attempts"])
        finally:
            if ended and thread:
                saver.delete_thread(thread)
    return True


def _release(job_id: UUID) -> None:
    """Put a claimed job back untouched: queued, its attempt returned, due after RETRY_STEP."""
    try:
        with _tx() as c:
            c.execute(
                "UPDATE jobs SET status = 'queued', attempts = attempts - 1, locked_at = NULL, "
                "run_after = now() + %s WHERE id = %s",
                (RETRY_STEP, job_id),
            )
    except Exception:  # noqa: BLE001 - the DB is down too: the stale sweep reclaims it later
        log.exception("could not release job %s", job_id)


def _try_status(tid: UUID, rid: UUID, status: str, message: str | None) -> None:
    try:
        _set_status(tid, rid, status, message)
    except ReportGone:
        pass


IDLE_S = 1  # ponytail: 1 s poll; LISTEN on a jobs channel if latency matters
MAX_BACKOFF_S = 30


def serve(iterations: int | None = None, sleep=time.sleep) -> None:
    """Run jobs forever. Nothing short of a stop signal ends this loop.

    A database restart, a network blip or a bug in one job must never take the worker
    down: the queue would sit untouched with nobody reading it. Errors are logged and
    retried with backoff (1, 2, 4 ... 30 s); the first success resets it.
    """
    backoff = 0
    n = 0
    while iterations is None or n < iterations:
        n += 1
        try:
            worked = run_once()
            backoff = 0
            if not worked:
                sleep(IDLE_S)
        except Exception:  # noqa: BLE001 - see docstring; KeyboardInterrupt still stops it
            log.exception("worker loop error; retrying")
            backoff = min(MAX_BACKOFF_S, backoff * 2 or 1)
            sleep(backoff)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    tracing.install_defaults()
    if not settings.worker_database_url or not settings.graph_database_url:
        raise SystemExit("WORKER_DATABASE_URL and GRAPH_DATABASE_URL are required")
    log.info("worker started")
    serve()


if __name__ == "__main__":
    main()
