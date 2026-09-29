import psycopg2
import psycopg2.extras
import psycopg2.pool

from .config import get_settings

_pool = None


class _LazyPool(psycopg2.pool.ThreadedConnectionPool):
    """Opens no connections at startup, but keeps up to `maxconn` idle ones for reuse.

    psycopg2's pools only keep a returned connection while fewer than `minconn` are idle and close the
    rest, so a plain minconn=0 pool closed every connection after one query and paid a fresh TLS handshake
    to Neon (~2 s) on every query - found live 2026-09-28, every screen endpoint took 2.5 s or more.
    minconn is only used at construction (to open connections) and when putting one back, so raising it
    after construction gives both: a lazy start and reuse.

    Connections are autocommit: query() and write() each send exactly one statement, and without autocommit
    psycopg2 adds a BEGIN and the pool code a ROLLBACK/COMMIT, i.e. three round trips to Neon (~0.3 s each
    from here) for every one-query request. commit()/rollback() below then send nothing to the server.
    """

    def __init__(self, maxconn: int, **kwargs):
        super().__init__(0, maxconn, **kwargs)  # 0: the API starts even if Neon is suspended or unreachable
        self.minconn = maxconn

    def _connect(self, key=None):
        conn = super()._connect(key)
        conn.autocommit = True
        return conn

    def drop_idle(self) -> None:
        """Closes every idle connection. Neon drops them all together when it suspends, so after one turns
        out dead the rest are too: without this, the retry picked up the next dead one and the request still
        failed (found live 2026-09-29 - three screen calls in a row got 503 after the app sat idle)."""
        with self._lock:
            idle, self._pool = self._pool, []
        for conn in idle:
            try:
                conn.close()
            except Exception:
                pass


def init_pool() -> None:
    """Nothing is opened here, so the API starts even if Neon is suspended or unreachable; /health reports it."""
    global _pool
    s = get_settings()
    _pool = _LazyPool(
        s.db_pool_max, dsn=s.database_url,
        connect_timeout=30, keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3,
    )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


def warm_pool(n: int) -> None:
    """Best-effort: opens a few connections ahead of the first request so a burst of concurrent requests (e.g. the
    Portfolio screen's initial load) isn't paying a fresh TLS handshake to Neon on every one of them. Never raises:
    if Neon is unreachable or asleep, this just gives up and the pool stays cold; /health still reports the outage.
    """
    opened = []
    for _ in range(n):
        try:
            opened.append(_pool.getconn())
        except Exception:
            break
    for conn in opened:
        _pool.putconn(conn)


def query(sql: str, params: tuple = ()) -> list:
    """Runs a read-only query and returns rows as dicts.

    Neon suspends idle databases and drops their connections, so a pooled connection can be dead
    when picked up: on a connection-level error the connection is discarded and the query retried once
    on a fresh one.
    """
    for attempt in (1, 2):
        conn = _pool.getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params or None)  # None: an empty tuple would still make psycopg2 parse '%' in the SQL
                rows = cur.fetchall()
            conn.rollback()  # end the implicit transaction so the pooled connection isn't left open in one
            _pool.putconn(conn)
            return rows
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            _pool.putconn(conn, close=True)
            _pool.drop_idle()  # the retry must open a fresh connection, not take another dead idle one
            if attempt == 2:
                raise
        except Exception:
            conn.rollback()
            _pool.putconn(conn)
            raise


def write(sql: str, params: tuple = (), returning: bool = True):
    """Runs one INSERT/UPDATE (optionally with RETURNING) in its own committed transaction.

    Same dead-connection handling as query(). The retry is safe here because a connection that dies
    before the statement completes never committed anything.
    """
    for attempt in (1, 2):
        conn = _pool.getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params or None)
                row = cur.fetchone() if returning else None
            conn.commit()
            _pool.putconn(conn)
            return row
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            _pool.putconn(conn, close=True)
            _pool.drop_idle()
            if attempt == 2:
                raise
        except Exception:
            conn.rollback()
            _pool.putconn(conn)
            raise


def query_one(sql: str, params: tuple = ()):
    rows = query(sql, params)
    return rows[0] if rows else None


def latest_rows(table: str, order_by: str, where: str = "", params: tuple = ()) -> list:
    """Rows of a Gold table for its most recent calculation_date.

    `table`, `order_by` and `where` are always string literals written in this codebase, never user
    input; anything user-supplied goes through `params`.
    """
    extra = f" AND {where}" if where else ""
    return query(
        f"SELECT * FROM {table} WHERE calculation_date = (SELECT max(calculation_date) FROM {table})"
        f"{extra} ORDER BY {order_by}",
        params,
    )
