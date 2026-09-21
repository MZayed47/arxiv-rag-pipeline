from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import aggregations, llm, rag, retrieval


@pytest.fixture(scope="session")
def client():
    """One client for the suite: the connection pool cannot be reopened."""
    with TestClient(app) as test_client:
        yield test_client


def test_root_lists_entrypoints(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"


def test_top_categories_returns_aggregated_rows(client, monkeypatch):
    monkeypatch.setattr(
        aggregations,
        "top_categories",
        lambda limit: [{"category": "cs.LG", "paper_count": 40, "primary_count": 25}],
    )

    response = client.get("/api/v1/stats/top-categories?limit=1")

    assert response.status_code == 200
    assert response.json() == [
        {"category": "cs.LG", "paper_count": 40, "primary_count": 25}
    ]


def test_papers_over_time_rejects_bad_granularity(client):
    response = client.get("/api/v1/stats/papers-over-time?granularity=week")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_ask_returns_answer_and_sources(client, monkeypatch):
    candidate = retrieval.Candidate(
        paper_id=1,
        arxiv_id="2401.12345",
        title="Retrieval Augmented Generation",
        abstract="We present a retrieval system.",
        primary_category="cs.IR",
        published_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        doi=None,
        journal_ref=None,
        vector_similarity=0.81,
        authors=["Ada Lovelace"],
    )
    monkeypatch.setattr(rag.retrieval, "retrieve", lambda question, top_k: [candidate])
    monkeypatch.setattr(rag.llm, "generate", lambda system, user: "RAG grounds answers [2401.12345].")

    response = client.post("/api/v1/ask", json={"question": "What is RAG?"})
    body = response.json()

    assert response.status_code == 200
    assert body["grounded"] is True
    assert body["sources"][0]["arxiv_id"] == "2401.12345"
    assert body["sources"][0]["url"] == "https://arxiv.org/abs/2401.12345"
    assert "2401.12345" in body["answer"]


def test_ask_is_honest_when_nothing_relevant_is_found(client, monkeypatch):
    weak = retrieval.Candidate(
        paper_id=2,
        arxiv_id="2402.00001",
        title="Unrelated paper",
        abstract="Something else entirely.",
        primary_category="cs.LG",
        published_at=None,
        doi=None,
        journal_ref=None,
        vector_similarity=0.01,
    )

    def fail_if_called(system, user):
        raise AssertionError("LLM must not be called without a good match")

    monkeypatch.setattr(rag.retrieval, "retrieve", lambda question, top_k: [weak])
    monkeypatch.setattr(rag.llm, "generate", fail_if_called)

    response = client.post("/api/v1/ask", json={"question": "How do I bake sourdough?"})
    body = response.json()

    assert response.status_code == 200
    assert body["grounded"] is False
    assert body["sources"] == []


def test_ask_reports_missing_llm_configuration(client, monkeypatch):
    candidate = retrieval.Candidate(
        paper_id=3,
        arxiv_id="2403.00002",
        title="Relevant paper",
        abstract="Highly relevant content.",
        primary_category="cs.AI",
        published_at=None,
        doi=None,
        journal_ref=None,
        vector_similarity=0.9,
    )

    def not_configured(system, user):
        raise llm.LLMNotConfigured("GEMINI_API_KEY is not set")

    monkeypatch.setattr(rag.retrieval, "retrieve", lambda question, top_k: [candidate])
    monkeypatch.setattr(rag.llm, "generate", not_configured)

    response = client.post("/api/v1/ask", json={"question": "Summarize the AI papers"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "http_error"


def test_ask_validates_short_questions(client):
    response = client.post("/api/v1/ask", json={"question": "hi"})

    assert response.status_code == 422
