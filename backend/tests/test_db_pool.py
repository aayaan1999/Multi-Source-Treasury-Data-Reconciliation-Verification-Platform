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
