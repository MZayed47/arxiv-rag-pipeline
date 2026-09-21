"""RAG API — natural-language questions answered from the ingested papers."""
import logging

from fastapi import APIRouter, HTTPException

from app.models import AskRequest, AskResponse
from app.services import llm, rag

log = logging.getLogger(__name__)

router = APIRouter(tags=["rag"])


@router.post("/ask", response_model=AskResponse)
def ask(request: AskRequest):
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")

    try:
        result = rag.answer_question(question, request.top_k)
    except llm.LLMNotConfigured as exc:
        log.error("LLM not configured: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Answer generation is not configured. Set an LLM API key in .env.",
        ) from exc
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}") from exc

    return AskResponse(question=question, **result)
