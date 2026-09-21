"""
Migration runner.

Applies every .sql file in migrations/ that has not been recorded in the
schema_migrations table, in filename order, each inside its own transaction.

    python -m app.db.migrate up
    python -m app.db.migrate status
"""
import logging
import sys
import time

import psycopg

from app.config import DATABASE_URL, MIGRATIONS_DIR
from app.logging_config import setup_logging

log = logging.getLogger(__name__)

_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def wait_for_db(attempts: int = 30, delay: float = 2.0) -> None:
    """Block until Postgres accepts connections; used on container startup."""
    for attempt in range(1, attempts + 1):
        try:
            with psycopg.connect(DATABASE_URL, connect_timeout=5):
                return
        except psycopg.OperationalError as exc:
            if attempt == attempts:
                raise RuntimeError(f"Database unreachable after {attempts} attempts") from exc
            log.info("Waiting for database (%s/%s)...", attempt, attempts)
            time.sleep(delay)


def _migration_files() -> list:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _applied_versions(conn) -> set[str]:
    conn.execute(_TRACKING_TABLE)
    conn.commit()
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row[0] for row in rows}


def apply_pending() -> list[str]:
    wait_for_db()
    applied: list[str] = []

    with psycopg.connect(DATABASE_URL) as conn:
        done = _applied_versions(conn)

        for path in _migration_files():
            version = path.stem
            if version in done:
                continue

            log.info("Applying migration %s", version)
            try:
                with conn.transaction():
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)", (version,)
                    )
            except Exception:
                log.exception("Migration %s failed", version)
                raise

            applied.append(version)

    if applied:
        log.info("Applied %d migration(s): %s", len(applied), ", ".join(applied))
    else:
        log.info("Schema already up to date")
    return applied


def status() -> None:
    wait_for_db()
    with psycopg.connect(DATABASE_URL) as conn:
        done = _applied_versions(conn)

    for path in _migration_files():
        marker = "applied" if path.stem in done else "pending"
        print(f"  [{marker:>7}] {path.stem}")


def main() -> None:
    setup_logging()
    command = sys.argv[1] if len(sys.argv) > 1 else "up"

    if command == "up":
        apply_pending()
    elif command == "status":
        status()
    else:
        print(f"Unknown command '{command}'. Use: up | status")
        sys.exit(1)


if __name__ == "__main__":
    main()
