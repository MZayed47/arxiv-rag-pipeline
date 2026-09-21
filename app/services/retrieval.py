"""
Hybrid retrieval over the papers table.

Two independent candidate lists are produced — pgvector cosine search over
abstract embeddings, and Postgres full-text search over title + abstract — and
fused with reciprocal rank fusion. Vector similarity is kept on each candidate
so the caller can decide whether the match is good enough to answer from.
"""
import logging
from dataclasses import dataclass, field

from app.config import (
    RAG_KEYWORD_CANDIDATES,
    RAG_MIN_SIMILARITY,
    RAG_VECTOR_CANDIDATES,
)
from app.db.pool import pool
from app.services import embeddings
from app.utils import to_pgvector

log = logging.getLogger(__name__)

RRF_K = 60
VECTOR_WEIGHT = 1.0
KEYWORD_WEIGHT = 0.7

_PAPER_COLS = """
    p.id,
    p.arxiv_id,
    p.title,
    p.abstract,
    c.code,
    p.published_at,
    p.doi,
    p.journal_ref
"""

_VECTOR_SQL = f"""
SELECT {_PAPER_COLS},
       1 - (e.embedding <=> %s::vector) AS similarity
FROM paper_embeddings e
JOIN papers p ON p.id = e.paper_id
LEFT JOIN categories c ON c.id = p.primary_category_id
ORDER BY e.embedding <=> %s::vector
LIMIT %s
"""

_KEYWORD_SQL = f"""
SELECT {_PAPER_COLS},
       ts_rank_cd(p.search_tsv, q.tsq) AS similarity
FROM papers p
LEFT JOIN categories c ON c.id = p.primary_category_id,
     websearch_to_tsquery('english', %s) AS q(tsq)
WHERE p.search_tsv @@ q.tsq
ORDER BY similarity DESC
LIMIT %s
"""

_AUTHORS_SQL = """
SELECT pa.paper_id, a.full_name
FROM paper_authors pa
JOIN authors a ON a.id = pa.author_id
WHERE pa.paper_id = ANY(%s)
ORDER BY pa.paper_id, pa.author_position
"""


@dataclass
class Candidate:
    paper_id: int
    arxiv_id: str
    title: str
    abstract: str
    primary_category: str | None
    published_at: object
    doi: str | None
    journal_ref: str | None
    vector_similarity: float = 0.0
    keyword_rank: float = 0.0
    fused_score: float = 0.0
    authors: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://arxiv.org/abs/{self.arxiv_id}"


def _row_to_candidate(row) -> Candidate:
    return Candidate(
        paper_id=row[0],
        arxiv_id=row[1],
        title=row[2],
        abstract=row[3],
        primary_category=row[4],
        published_at=row[5],
        doi=row[6],
        journal_ref=row[7],
    )


def fuse(vector_hits: list[Candidate], keyword_hits: list[Candidate]) -> list[Candidate]:
    """Reciprocal rank fusion of the two candidate lists, best first."""
    merged: dict[int, Candidate] = {}

    for rank, candidate in enumerate(vector_hits, start=1):
        merged[candidate.paper_id] = candidate
        candidate.fused_score += VECTOR_WEIGHT / (RRF_K + rank)

    for rank, candidate in enumerate(keyword_hits, start=1):
        existing = merged.get(candidate.paper_id)
        if existing is None:
            merged[candidate.paper_id] = candidate
            existing = candidate
        else:
            existing.keyword_rank = candidate.keyword_rank
        existing.fused_score += KEYWORD_WEIGHT / (RRF_K + rank)

    return sorted(merged.values(), key=lambda c: c.fused_score, reverse=True)


def is_weak_match(candidates: list[Candidate]) -> bool:
    """True when nothing retrieved is close enough to answer from."""
    if not candidates:
        return True
    best_vector = max(c.vector_similarity for c in candidates)
    has_keyword_hit = any(c.keyword_rank > 0 for c in candidates)
    return best_vector < RAG_MIN_SIMILARITY and not has_keyword_hit


def _attach_authors(conn, candidates: list[Candidate]) -> None:
    if not candidates:
        return
    by_id = {c.paper_id: c for c in candidates}
    rows = conn.execute(_AUTHORS_SQL, (list(by_id),)).fetchall()
    for paper_id, full_name in rows:
        by_id[paper_id].authors.append(full_name)


def retrieve(question: str, top_k: int) -> list[Candidate]:
    """Return the top_k most relevant papers for a natural-language question."""
    query_vector = to_pgvector(embeddings.embed_query(question))

    with pool.connection() as conn:
        vector_rows = conn.execute(
            _VECTOR_SQL, (query_vector, query_vector, RAG_VECTOR_CANDIDATES)
        ).fetchall()

        vector_hits = []
        for row in vector_rows:
            candidate = _row_to_candidate(row)
            candidate.vector_similarity = float(row[8])
            vector_hits.append(candidate)

        keyword_hits = []
        try:
            keyword_rows = conn.execute(
                _KEYWORD_SQL, (question, RAG_KEYWORD_CANDIDATES)
            ).fetchall()
            for row in keyword_rows:
                candidate = _row_to_candidate(row)
                candidate.keyword_rank = float(row[8])
                keyword_hits.append(candidate)
        except Exception as exc:
            # A malformed tsquery should degrade to vector-only, not 500.
            log.warning("Keyword search failed for %r: %s", question, exc)

        log.info(
            "Retrieval for %r: %d vector hits, %d keyword hits",
            question[:80], len(vector_hits), len(keyword_hits),
        )

        candidates = fuse(vector_hits, keyword_hits)[:top_k]
        _attach_authors(conn, candidates)

    return candidates
