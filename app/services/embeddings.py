"""
Local sentence-transformers embedding model.

The model is loaded lazily on first use and kept as a module-level singleton so
the API and the ingestion CLI each pay the load cost once.
"""
import logging
import threading

from app.config import EMBEDDING_BATCH_SIZE, EMBEDDING_DIM, EMBEDDING_MODEL

log = logging.getLogger(__name__)

_model = None
_lock = threading.Lock()


def get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                log.info("Loading embedding model %s", EMBEDDING_MODEL)
                model = SentenceTransformer(EMBEDDING_MODEL)
                dim = model.get_sentence_embedding_dimension()
                if dim != EMBEDDING_DIM:
                    raise RuntimeError(
                        f"Model {EMBEDDING_MODEL} produces {dim}-dim vectors but the "
                        f"schema expects {EMBEDDING_DIM}. Update EMBEDDING_DIM and "
                        f"the vector column in migrations/0001_initial_schema.sql."
                    )
                _model = model
                log.info("Embedding model ready (dim=%d)", dim)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors = get_model().encode(
        texts,
        batch_size=EMBEDDING_BATCH_SIZE,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return [vector.tolist() for vector in vectors]


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def build_embedding_text(title: str, abstract: str) -> str:
    """Title plus abstract is the unit we embed and retrieve on."""
    return f"{title.strip()}\n\n{abstract.strip()}".strip()
