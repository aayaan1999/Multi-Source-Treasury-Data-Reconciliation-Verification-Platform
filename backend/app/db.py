import psycopg2
import psycopg2.extras
import psycopg2.pool

from .config import get_settings

_pool = None


def init_pool() -> None:
    """minconn=0: the API starts even if Neon is suspended or unreachable; /health reports it."""
    global _pool
    s = get_settings()
    _pool = psycopg2.pool.ThreadedConnectionPool(
        0, s.db_pool_max, dsn=s.database_url,
        connect_timeout=30, keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3,
    )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


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
