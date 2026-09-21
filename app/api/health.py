from fastapi import APIRouter

from app.db import pool as db
from app.services import llm

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    """Liveness plus a quick dependency check."""
    db_ok = db.ping()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "up" if db_ok else "down",
        "llm_configured": llm.is_configured(),
    }
