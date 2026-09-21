"""
RAG answer generation: retrieve relevant papers, build a grounded prompt, and
ask the LLM. When retrieval finds nothing close enough, the question is
answered honestly instead of being passed to the model.
"""
import logging

from app.config import RAG_TOP_K
from app.services import llm, retrieval

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You answer questions about a dataset of arXiv papers.

Rules:
- Use only the papers given in CONTEXT. Never invent papers, authors, numbers or findings.
- Cite the papers you use by their arXiv id in square brackets, e.g. [2401.01234].
- If the context does not contain enough information to answer, say so plainly and
  describe what the retrieved papers do cover instead.
- Be concise and factual. No preamble about being an AI."""

NO_MATCH_ANSWER = (
    "I could not find any papers in this dataset that are relevant to your question, "
    "so I do not have grounded material to answer from. The dataset only covers a "
    "sample of recent arXiv papers, so the topic may simply not be represented."
)

EMPTY_INDEX_ANSWER = (
    "The paper index is empty. Run the ingestion command to download papers and "
    "build the embeddings before asking questions."
)


def build_context(candidates: list[retrieval.Candidate]) -> str:
    blocks = []
    for candidate in candidates:
        authors = ", ".join(candidate.authors[:8]) or "unknown"
        if len(candidate.authors) > 8:
            authors += " et al."
        published = candidate.published_at.date().isoformat() if candidate.published_at else "unknown"
        blocks.append(
            f"[{candidate.arxiv_id}] {candidate.title}\n"
            f"Authors: {authors}\n"
            f"Primary category: {candidate.primary_category or 'unknown'} | "
            f"Published: {published}\n"
            f"Abstract: {candidate.abstract}"
        )
    return "\n\n---\n\n".join(blocks)


def answer_question(question: str, top_k: int | None = None) -> dict:
    top_k = top_k or RAG_TOP_K
    candidates = retrieval.retrieve(question, top_k)

    if not candidates:
        return {"answer": EMPTY_INDEX_ANSWER, "sources": [], "grounded": False}

    if retrieval.is_weak_match(candidates):
        log.info("No sufficiently relevant papers for %r", question[:80])
        return {"answer": NO_MATCH_ANSWER, "sources": [], "grounded": False}

    user_prompt = (
        f"CONTEXT:\n{build_context(candidates)}\n\n"
        f"QUESTION: {question}\n\n"
        "Answer using only the context above and cite arXiv ids."
    )

    answer = llm.generate(SYSTEM_PROMPT, user_prompt)
    if not answer:
        answer = NO_MATCH_ANSWER
        return {"answer": answer, "sources": [], "grounded": False}

    sources = [
        {
            "arxiv_id": c.arxiv_id,
            "title": c.title,
            "authors": c.authors,
            "primary_category": c.primary_category,
            "published": c.published_at,
            "score": round(c.vector_similarity, 4),
            "url": c.url,
        }
        for c in candidates
    ]
    return {"answer": answer, "sources": sources, "grounded": True}
