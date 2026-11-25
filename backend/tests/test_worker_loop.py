import psycopg
import pytest

from app import worker


def test_loop_survives_database_outage_and_backs_off(monkeypatch):
    outcomes = iter([psycopg.OperationalError("the database system is shutting down"),
                     psycopg.OperationalError("connection refused"),
                     True, False])

    def fake_run_once():
        o = next(outcomes)
        if isinstance(o, BaseException):
            raise o
        return o

    monkeypatch.setattr(worker, "run_once", fake_run_once)
    slept = []
    worker.serve(iterations=4, sleep=slept.append)
    assert slept == [1, 2, worker.IDLE_S]  # backoff 1, 2; reset after success; idle poll


def test_backoff_is_capped(monkeypatch):
    def down():
        raise psycopg.OperationalError("down")

    monkeypatch.setattr(worker, "run_once", down)
    slept = []
    worker.serve(iterations=8, sleep=slept.append)
    assert slept[-1] == worker.MAX_BACKOFF_S and max(slept) == worker.MAX_BACKOFF_S


def test_unexpected_error_does_not_kill_the_loop(monkeypatch):
    outcomes = iter([RuntimeError("bug in one job"), False])

    def fake():
        o = next(outcomes)
        if isinstance(o, BaseException):
            raise o
        return o

    monkeypatch.setattr(worker, "run_once", fake)
    worker.serve(iterations=2, sleep=lambda s: None)


def test_keyboard_interrupt_still_stops_it(monkeypatch):
    def stop():
        raise KeyboardInterrupt

    monkeypatch.setattr(worker, "run_once", stop)
    with pytest.raises(KeyboardInterrupt):
        worker.serve(iterations=3, sleep=lambda s: None)
