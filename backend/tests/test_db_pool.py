"""The connection pool opens nothing at startup but reuses connections afterwards (app/db.py _LazyPool)."""
import psycopg2
import psycopg2.extensions

from app import db


class _FakeConn:
    closed = False
    autocommit = False

    class info:
        transaction_status = psycopg2.extensions.TRANSACTION_STATUS_IDLE

    def close(self):
        self.closed = True


def _fake_pool(monkeypatch, maxconn=3):
    opened = []

    def fake_connect(*args, **kwargs):
        conn = _FakeConn()
        opened.append(conn)
        return conn

    monkeypatch.setattr(psycopg2, "connect", fake_connect)
    return db._LazyPool(maxconn, dsn="postgresql://unused"), opened


def test_nothing_opened_at_startup(monkeypatch):
    _, opened = _fake_pool(monkeypatch)
    assert opened == []


def test_returned_connection_is_reused_not_closed(monkeypatch):
    pool, opened = _fake_pool(monkeypatch)
    first = pool.getconn()
    pool.putconn(first)
    second = pool.getconn()
    assert second is first
    assert not first.closed
    assert len(opened) == 1


def test_connections_are_autocommit(monkeypatch):
    pool, _ = _fake_pool(monkeypatch)
    assert pool.getconn().autocommit is True


def test_close_flag_still_discards_a_dead_connection(monkeypatch):
    pool, opened = _fake_pool(monkeypatch)
    conn = pool.getconn()
    pool.putconn(conn, close=True)
    assert conn.closed
    assert pool.getconn() is not conn
    assert len(opened) == 2


def test_after_a_dead_connection_the_retry_gets_a_fresh_one_not_another_dead_idle_one(monkeypatch):
    """Found live 2026-09-29: Neon drops every idle connection when it suspends; the retry used to pick up
    the next dead idle connection, so the request failed with 503 anyway."""
    pool, opened = _fake_pool(monkeypatch)
    idle = [pool.getconn() for _ in range(3)]
    for conn in idle:
        pool.putconn(conn)                                  # three idle connections, all about to be dead
    served = []

    class _Cursor:
        def __init__(self, conn):
            self.conn = conn

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params):
            served.append(self.conn)
            if self.conn in idle:
                raise psycopg2.OperationalError("could not receive data from server")

        def fetchall(self):
            return [{"ok": 1}]

    monkeypatch.setattr(_FakeConn, "cursor", lambda self, cursor_factory=None: _Cursor(self), raising=False)
    monkeypatch.setattr(_FakeConn, "rollback", lambda self: None, raising=False)
    monkeypatch.setattr(db, "_pool", pool)
    assert db.query("SELECT 1") == [{"ok": 1}]
    assert served[0] in idle and served[1] not in idle     # the retry opened a new connection
    assert all(conn.closed for conn in idle)                # and the other dead ones were thrown away


def test_a_request_waits_for_a_free_connection_instead_of_failing(monkeypatch):
    """Found 2026-09-29 (a flaky /health test): while warm_pool() held every connection at startup, a request
    got "connection pool exhausted" at once; now it waits for one to come back."""
    import threading
    import time

    import psycopg2.pool
    pool, _ = _fake_pool(monkeypatch, maxconn=1)
    held = pool.getconn()
    threading.Timer(0.1, lambda: pool.putconn(held)).start()
    started = time.monotonic()
    assert pool.getconn() is held
    assert time.monotonic() - started >= 0.05

    monkeypatch.setattr(db, "WAIT_SECONDS", 0.05)
    try:
        pool.getconn()                                   # still held, and the wait runs out
        raise AssertionError("expected the pool to give up")
    except psycopg2.pool.PoolError as e:
        assert "exhausted" in str(e)
