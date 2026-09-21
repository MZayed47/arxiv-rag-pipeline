"""
Embedding refresh.

Selects papers whose vector is missing, was built by a different model, or whose
title/abstract hash no longer matches, then re-embeds them in batches. This is
what keeps the RAG index consistent after an incremental ingestion run.
"""
import logging

from app.config import EMBEDDING_MODEL
from app.services.embeddings import build_embedding_text, embed_texts
from app.utils import to_pgvector

log = logging.getLogger(__name__)

_UPSERT_SQL = """
INSERT INTO paper_embeddings (paper_id, embedding, model, source_hash)
VALUES (%s, %s::vector, %s, %s)
ON CONFLICT (paper_id) DO UPDATE SET
    embedding   = EXCLUDED.embedding,
    model       = EXCLUDED.model,
    source_hash = EXCLUDED.source_hash,
    created_at  = NOW()
"""


def _stale_papers(conn) -> list[tuple[int, str, str]]:
    """Papers whose vector is missing, stale, or built by another model."""
    from ingestion.preprocess import compute_source_hash

    sql = """
    SELECT p.id, p.title, p.abstract, e.model, e.source_hash
    FROM papers p
    LEFT JOIN paper_embeddings e ON e.paper_id = p.id
    ORDER BY p.id
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    stale = []
    for paper_id, title, abstract, model, source_hash in rows:
        current_hash = compute_source_hash(title, abstract)
        if model != EMBEDDING_MODEL or source_hash != current_hash:
            stale.append((paper_id, title, abstract))
    return stale


def refresh_embeddings(conn, batch_size: int = 128) -> int:
    """Embed every stale paper. Returns the number of vectors written."""
    from ingestion.preprocess import compute_source_hash

    stale = _stale_papers(conn)
    if not stale:
        log.info("All embeddings are up to date")
        return 0

    log.info("Embedding %d paper(s) with %s", len(stale), EMBEDDING_MODEL)
    written = 0

    for start in range(0, len(stale), batch_size):
        batch = stale[start:start + batch_size]
        texts = [build_embedding_text(title, abstract) for _, title, abstract in batch]
        vectors = embed_texts(texts)

        with conn.cursor() as cur:
            for (paper_id, title, abstract), vector in zip(batch, vectors):
                cur.execute(
                    _UPSERT_SQL,
                    (
                        paper_id,
                        to_pgvector(vector),
                        EMBEDDING_MODEL,
                        compute_source_hash(title, abstract),
                    ),
                )
                written += 1
        conn.commit()
        log.info("  embedded %d/%d", min(start + batch_size, len(stale)), len(stale))

    return written


def clear_embeddings(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE paper_embeddings")
    conn.commit()
    log.info("Embeddings cleared")
