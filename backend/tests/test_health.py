import psycopg
import pytest

from app.config import settings


def _jobs(sql: str, *args):
    # worker role: sees every tenant's jobs
    with psycopg.connect(settings.worker_database_url) as c:
        c.execute(sql, args)


@pytest.fixture
def empty_queue(db_urls):
    """Other tests leave jobs behind; health counts every tenant's queue."""
    _jobs("UPDATE jobs SET status = 'done' WHERE status IN ('queued', 'running')")
    yield
    _jobs("UPDATE jobs SET status = 'done' WHERE status IN ('queued', 'running')")


def _add(tid, status="queued", waited="0 s", locked=None):
    _jobs(
        "INSERT INTO jobs (tenant_id, kind, status, run_after, locked_at) "
        "VALUES (%s, 'test', %s, now() - %s::interval, now() - %s::interval)",
        tid, status, waited, locked,
    )


def test_health_ok_with_empty_queue(client, empty_queue):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "queued": 0, "oldest_wait_s": 0}


def test_health_counts_every_tenants_queue(client, lab, empty_queue):
    # /health runs as hc_app with no tenant; the job belongs to some other lab
    _add(lab[1], waited="1 minute")
    _add(lab[1])
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["queued"] == 2
    assert 55 <= body["oldest_wait_s"] <= 120


def test_a_backlog_is_not_a_stall(client, lab, empty_queue):
    # one worker, a lab uploads 10 reports at once: the last waits minutes, nothing is wrong
    _add(lab[1], waited="6 minutes")
    assert client.get("/health").json()["status"] == "ok"


def test_health_unhealthy_when_a_job_waits_too_long(client, lab, empty_queue):
    _add(lab[1], waited="16 minutes")
    r = client.get("/health")
    assert r.status_code == 503 and r.json()["status"] == "stalled"


def test_health_unhealthy_when_a_job_runs_too_long(client, lab, empty_queue):
    # the worker hung mid-job: nothing is queued, yet the report never finishes
    _add(lab[1], status="running", locked="16 minutes")
    r = client.get("/health")
    assert r.status_code == 503 and r.json()["queued"] == 1


def test_jobs_waiting_for_consent_or_retry_do_not_count(client, lab, empty_queue):
    _add(lab[1], status="waiting_consent", waited="1 hour")
    _add(lab[1], waited="-1 hour")  # retry scheduled in the future
    assert client.get("/health").json() == {"status": "ok", "queued": 0, "oldest_wait_s": 0}


def test_health_survives_a_database_restart(client, empty_queue):
    # a DB restart kills every pooled connection; the next request must not 500
    assert client.get("/health").status_code == 200
    with psycopg.connect(settings.admin_database_url, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                      "WHERE usename = 'hc_app' AND datname = 'hc_test'")
    assert client.get("/health").status_code == 200
