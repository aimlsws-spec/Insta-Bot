"""
MySQL database layer — drop-in replacement for the previous SQLite setup.

Provides:
  get_db()        — context manager that yields a _DBWrapper (for main.py / FastAPI endpoints)
  get_connection() — returns a raw pymysql DictCursor connection (for utility scripts)

The _DBWrapper mimics sqlite3.Connection.execute() so that every call site
in main.py that does:
    with get_db() as conn:
        cursor = conn.execute("SELECT ... WHERE id = ?", (some_id,))
        row    = cursor.fetchone()
        conn.commit()
continues to work without any changes to the calling code.
Placeholder conversion (?  →  %s) is handled transparently inside execute().
"""

import os
import pymysql
import pymysql.cursors
from contextlib import contextmanager

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional at import time; env vars may be set by the OS

# ─── Connection parameters ────────────────────────────────────────────────────

_DB_CONFIG: dict = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "3306")),
    "user":     os.getenv("DB_USER",     "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME",     "instagram_bot"),
    "charset":  "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": False,
}


# ─── SQLite-compatible wrapper ────────────────────────────────────────────────

class _DBWrapper:
    """
    Wraps a pymysql connection to expose the same .execute() interface that
    sqlite3.Connection provides.  Every call returns the internal DictCursor so
    .fetchone() / .fetchall() work identically for the caller.

    Why a single shared cursor?  All existing call sites either:
      a) immediately call fetchone()/fetchall() before the next execute(), or
      b) assign the result to a new variable and fully drain it.
    Re-using one cursor is therefore safe and avoids the overhead of creating
    a new cursor for every statement.
    """

    def __init__(self, raw_conn: pymysql.connections.Connection) -> None:
        self._conn = raw_conn
        self._cur  = raw_conn.cursor()

    # ------------------------------------------------------------------
    def execute(self, sql: str, params=None):
        """Execute *sql*, converting SQLite '?' placeholders to MySQL '%s'."""
        sql = sql.replace("?", "%s")
        self._cur.execute(sql, params or ())
        return self._cur

    # ------------------------------------------------------------------
    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        try:
            self._cur.close()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass


# ─── Public API ──────────────────────────────────────────────────────────────

@contextmanager
def get_db():
    """
    Context manager for FastAPI endpoints and main.py helpers.

    Usage (identical to the old SQLite usage):
        with get_db() as conn:
            cursor = conn.execute("SELECT * FROM users WHERE id = ?", (uid,))
            row    = cursor.fetchone()
            conn.commit()
    """
    raw_conn = pymysql.connect(**_DB_CONFIG)
    wrapper  = _DBWrapper(raw_conn)
    try:
        yield wrapper
    except Exception:
        wrapper.rollback()
        raise
    finally:
        wrapper.close()


def get_connection() -> pymysql.connections.Connection:
    """
    Return a raw pymysql connection (DictCursor) for use in stand-alone utility
    scripts that manage their own cursor lifecycle.

    Caller is responsible for conn.commit() and conn.close().
    """
    return pymysql.connect(**_DB_CONFIG)
