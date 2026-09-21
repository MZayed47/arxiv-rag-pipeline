"""
Central configuration. Every environment variable is read here once so the rest
of the codebase imports typed constants instead of calling os.getenv().
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# --- Database --------------------------------------------------------------
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "arxiv_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

DATABASE_URL = os.getenv("DATABASE_URL") or (
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

DB_POOL_MIN_SIZE = int(os.getenv("DB_POOL_MIN_SIZE", "1"))
DB_POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX_SIZE", "10"))

MIGRATIONS_DIR = ROOT / "migrations"

# --- API -------------------------------------------------------------------
API_PORT = int(os.getenv("API_PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
RUN_MIGRATIONS_ON_STARTUP = _bool("RUN_MIGRATIONS_ON_STARTUP", True)

# --- arXiv source ----------------------------------------------------------
ARXIV_API_URL = os.getenv("ARXIV_API_URL", "https://export.arxiv.org/api/query")
ARXIV_CATEGORIES = _csv("ARXIV_CATEGORIES", "cs.AI,cs.LG,cs.CL,cs.CV,cs.IR")
ARXIV_PAPERS_PER_CATEGORY = int(os.getenv("ARXIV_PAPERS_PER_CATEGORY", "200"))
ARXIV_BATCH_SIZE = int(os.getenv("ARXIV_BATCH_SIZE", "200"))
ARXIV_REQUEST_DELAY = float(os.getenv("ARXIV_REQUEST_DELAY", "3.0"))
ARXIV_TIMEOUT = int(os.getenv("ARXIV_TIMEOUT", "60"))
ARXIV_MAX_RETRIES = int(os.getenv("ARXIV_MAX_RETRIES", "5"))
ARXIV_CONTACT_EMAIL = os.getenv("ARXIV_CONTACT_EMAIL", "you@example.com")
ARXIV_USER_AGENT = (
    f"ArxivRagPipeline/1.0 (research assignment; contact: {ARXIV_CONTACT_EMAIL})"
)

# --- Embeddings ------------------------------------------------------------
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))

# --- LLM -------------------------------------------------------------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "1024"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# --- RAG tuning ------------------------------------------------------------
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
RAG_MAX_TOP_K = int(os.getenv("RAG_MAX_TOP_K", "15"))
RAG_VECTOR_CANDIDATES = int(os.getenv("RAG_VECTOR_CANDIDATES", "25"))
RAG_KEYWORD_CANDIDATES = int(os.getenv("RAG_KEYWORD_CANDIDATES", "25"))
RAG_MIN_SIMILARITY = float(os.getenv("RAG_MIN_SIMILARITY", "0.25"))
