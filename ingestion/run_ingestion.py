"""
Ingestion CLI.

    python -m ingestion.run_ingestion ingest
    python -m ingestion.run_ingestion ingest --categories cs.AI,cs.LG --per-category 300
    python -m ingestion.run_ingestion ingest --sort-by lastUpdatedDate   # refresh run
    python -m ingestion.run_ingestion ingest --skip-embeddings
    python -m ingestion.run_ingestion embed
    python -m ingestion.run_ingestion reset --yes
    python -m ingestion.run_ingestion stats

Ingestion is safe to re-run: papers are upserted on arxiv_id, unchanged papers
are skipped, and only stale embeddings are regenerated.
"""
import argparse
import logging
import sys
import time

from app.config import ARXIV_CATEGORIES, ARXIV_PAPERS_PER_CATEGORY, ARXIV_REQUEST_DELAY
from app.db.migrate import apply_pending
from app.db.pool import connect
from app.logging_config import setup_logging
from ingestion import repository
from ingestion.arxiv_client import ArxivClient, ArxivError
from ingestion.embedder import clear_embeddings, refresh_embeddings

log = logging.getLogger(__name__)


def ingest(args) -> int:
    categories = (
        [c.strip() for c in args.categories.split(",") if c.strip()]
        if args.categories
        else ARXIV_CATEGORIES
    )
    per_category = args.per_category or ARXIV_PAPERS_PER_CATEGORY

    log.info(
        "Ingesting %d paper(s) per category from %s (sort=%s)",
        per_category, ", ".join(categories), args.sort_by,
    )

    client = ArxivClient(delay=args.delay)
    stats = {"inserted": 0, "updated": 0, "unchanged": 0, "failed": 0}
    started = time.monotonic()

    conn = connect()
    try:
        for index, category in enumerate(categories, start=1):
            log.info("--- category %d/%d: %s ---", index, len(categories), category)
            try:
                records = client.iter_category(
                    category,
                    target_count=per_category,
                    sort_by=args.sort_by,
                    primary_only=not args.allow_cross_listed,
                )
                for record in records:
                    try:
                        status = repository.upsert_paper(conn, record)
                        conn.commit()
                        stats[status] += 1
                    except Exception:
                        # One bad record must not abort the whole run.
                        conn.rollback()
                        stats["failed"] += 1
                        log.exception("Failed to store paper %s", record.arxiv_id)
            except ArxivError:
                log.exception("Category %s aborted; continuing with the rest", category)

        log.info(
            "Ingestion finished in %.1fs — inserted=%d updated=%d unchanged=%d failed=%d",
            time.monotonic() - started, stats["inserted"], stats["updated"],
            stats["unchanged"], stats["failed"],
        )

        if args.skip_embeddings:
            log.info("Skipping embedding refresh (--skip-embeddings)")
        else:
            written = refresh_embeddings(conn)
            log.info("Embeddings refreshed: %d", written)

        _print_counts(conn)
    finally:
        conn.close()

    return 1 if stats["failed"] and not (stats["inserted"] or stats["updated"]) else 0


def embed(args) -> int:
    conn = connect()
    try:
        if args.rebuild:
            clear_embeddings(conn)
        written = refresh_embeddings(conn)
        log.info("Embeddings written: %d", written)
        _print_counts(conn)
    finally:
        conn.close()
    return 0


def reset(args) -> int:
    if not args.yes:
        answer = input("This deletes all papers, authors, categories and embeddings. Type 'yes' to continue: ")
        if answer.strip().lower() != "yes":
            log.info("Aborted")
            return 1

    conn = connect()
    try:
        repository.wipe_dataset(conn)
        conn.commit()
        _print_counts(conn)
    finally:
        conn.close()
    return 0


def stats(args) -> int:
    conn = connect()
    try:
        _print_counts(conn)
    finally:
        conn.close()
    return 0


def _print_counts(conn) -> None:
    for key, value in repository.counts(conn).items():
        print(f"  {key:<28} {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="arXiv ingestion pipeline")
    parser.add_argument(
        "--skip-migrations", action="store_true", help="do not apply pending migrations first"
    )
    sub = parser.add_subparsers(dest="command")

    p_ingest = sub.add_parser("ingest", help="fetch papers from arXiv and store them")
    p_ingest.add_argument("--categories", help="comma separated, e.g. cs.AI,cs.LG")
    p_ingest.add_argument("--per-category", type=int, help="papers per category")
    p_ingest.add_argument("--delay", type=float, default=ARXIV_REQUEST_DELAY)
    p_ingest.add_argument(
        "--sort-by",
        default="submittedDate",
        choices=["submittedDate", "lastUpdatedDate"],
        help="use lastUpdatedDate to pick up revised papers",
    )
    p_ingest.add_argument("--allow-cross-listed", action="store_true")
    p_ingest.add_argument("--skip-embeddings", action="store_true")
    p_ingest.set_defaults(func=ingest)

    p_embed = sub.add_parser("embed", help="regenerate stale embeddings")
    p_embed.add_argument("--rebuild", action="store_true", help="drop all vectors first")
    p_embed.set_defaults(func=embed)

    p_reset = sub.add_parser("reset", help="wipe the dataset (papers, authors, categories, embeddings)")
    p_reset.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p_reset.set_defaults(func=reset)

    p_stats = sub.add_parser("stats", help="print row counts")
    p_stats.set_defaults(func=stats)

    return parser


def main() -> None:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args()

    if not getattr(args, "func", None):
        parser.print_help()
        sys.exit(1)

    if not args.skip_migrations:
        apply_pending()

    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
