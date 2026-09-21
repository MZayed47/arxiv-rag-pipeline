"""
Database writes for ingestion.

Upserts are keyed on arxiv_id, so re-running ingestion is safe: an unchanged
paper is only touched to bump last_synced_at, a changed paper has its row and
its author/category links rewritten, and a new paper is inserted.
"""
import logging

from ingestion.preprocess import PaperRecord, normalize_author

log = logging.getLogger(__name__)

STATUS_INSERTED = "inserted"
STATUS_UPDATED = "updated"
STATUS_UNCHANGED = "unchanged"


def _get_or_create_category(cur, code: str) -> int:
    cur.execute(
        """
        INSERT INTO categories (code) VALUES (%s)
        ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code
        RETURNING id
        """,
        (code,),
    )
    return cur.fetchone()[0]


def _get_or_create_author(cur, full_name: str) -> int:
    cur.execute(
        """
        INSERT INTO authors (full_name, normalized_name) VALUES (%s, %s)
        ON CONFLICT (normalized_name) DO UPDATE SET full_name = EXCLUDED.full_name
        RETURNING id
        """,
        (full_name, normalize_author(full_name)),
    )
    return cur.fetchone()[0]


def _link_authors(cur, paper_id: int, authors: list[str]) -> None:
    cur.execute("DELETE FROM paper_authors WHERE paper_id = %s", (paper_id,))
    for position, full_name in enumerate(authors, start=1):
        author_id = _get_or_create_author(cur, full_name)
        cur.execute(
            """
            INSERT INTO paper_authors (paper_id, author_id, author_position)
            VALUES (%s, %s, %s)
            ON CONFLICT (paper_id, author_id) DO NOTHING
            """,
            (paper_id, author_id, position),
        )


def _link_categories(cur, paper_id: int, categories: list[str], primary: str | None) -> None:
    cur.execute("DELETE FROM paper_categories WHERE paper_id = %s", (paper_id,))
    for code in categories:
        category_id = _get_or_create_category(cur, code)
        cur.execute(
            """
            INSERT INTO paper_categories (paper_id, category_id, is_primary)
            VALUES (%s, %s, %s)
            ON CONFLICT (paper_id, category_id)
            DO UPDATE SET is_primary = EXCLUDED.is_primary
            """,
            (paper_id, category_id, code == primary),
        )


def upsert_paper(conn, record: PaperRecord) -> str:
    """Insert or update one paper and its links. Returns the applied status."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, content_hash FROM papers WHERE arxiv_id = %s", (record.arxiv_id,)
        )
        existing = cur.fetchone()

        if existing and existing[1] == record.content_hash:
            cur.execute(
                "UPDATE papers SET last_synced_at = NOW() WHERE id = %s", (existing[0],)
            )
            return STATUS_UNCHANGED

        primary_id = (
            _get_or_create_category(cur, record.primary_category)
            if record.primary_category
            else None
        )

        cur.execute(
            """
            INSERT INTO papers (
                arxiv_id, title, abstract, primary_category_id,
                published_at, updated_at, doi, journal_ref, content_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (arxiv_id) DO UPDATE SET
                title               = EXCLUDED.title,
                abstract            = EXCLUDED.abstract,
                primary_category_id = EXCLUDED.primary_category_id,
                published_at        = EXCLUDED.published_at,
                updated_at          = EXCLUDED.updated_at,
                doi                 = EXCLUDED.doi,
                journal_ref         = EXCLUDED.journal_ref,
                content_hash        = EXCLUDED.content_hash,
                last_synced_at      = NOW()
            RETURNING id
            """,
            (
                record.arxiv_id,
                record.title,
                record.abstract,
                primary_id,
                record.published_at,
                record.updated_at,
                record.doi,
                record.journal_ref,
                record.content_hash,
            ),
        )
        paper_id = cur.fetchone()[0]

        _link_authors(cur, paper_id, record.authors)
        _link_categories(cur, paper_id, record.categories, record.primary_category)

    return STATUS_UPDATED if existing else STATUS_INSERTED


def wipe_dataset(conn) -> None:
    """Remove papers, authors, categories and embeddings, keeping the schema."""
    with conn.cursor() as cur:
        cur.execute(
            """
            TRUNCATE TABLE paper_embeddings, paper_authors, paper_categories,
                           papers, authors, categories
            RESTART IDENTITY CASCADE
            """
        )
    log.info("Dataset wiped")


def counts(conn) -> dict:
    sql = """
    SELECT
        (SELECT COUNT(*) FROM papers),
        (SELECT COUNT(*) FROM authors),
        (SELECT COUNT(*) FROM categories),
        (SELECT COUNT(*) FROM paper_embeddings),
        (SELECT COUNT(*) FROM papers p
           LEFT JOIN paper_embeddings e ON e.paper_id = p.id
          WHERE e.paper_id IS NULL)
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()

    return {
        "papers": row[0],
        "authors": row[1],
        "categories": row[2],
        "embeddings": row[3],
        "papers_without_embeddings": row[4],
    }
