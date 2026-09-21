"""
Module-level psycopg connection pool.

API handlers are defined as sync functions, so FastAPI runs them in its
threadpool and a synchronous pool is both sufficient and simpler to reason
about than mixing sync ingestion code with an async pool.
"""
import logging

import psycopg
from psycopg_pool import ConnectionPool

from app.config import DATABASE_URL, DB_POOL_MAX_SIZE, DB_POOL_MIN_SIZE

log = logging.getLogger(__name__)

_KEEPALIVE_KWARGS = {
    "keepalives": 1,
    "keepalives_idle": 60,
    "keepalives_interval": 10,
    "keepalives_count": 5,
}

pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=DB_POOL_MIN_SIZE,
    max_size=DB_POOL_MAX_SIZE,
    kwargs=_KEEPALIVE_KWARGS,
    open=False,
)


def connect() -> psycopg.Connection:
    """Standalone connection for CLI tools that run outside the API process."""
    return psycopg.connect(DATABASE_URL, **_KEEPALIVE_KWARGS)


def ping() -> bool:
    try:
        with pool.connection(timeout=5) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception as exc:
        log.warning("Database ping failed: %s", exc)
        return False
