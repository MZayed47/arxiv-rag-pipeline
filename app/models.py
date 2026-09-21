"""Pydantic request and response models for both APIs."""
from datetime import datetime

from pydantic import BaseModel, Field


# --- RAG -------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=15)


class Source(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str]
    primary_category: str | None
    published: datetime | None
    score: float
    url: str


class AskResponse(BaseModel):
    question: str
    answer: str
    sources: list[Source]
    grounded: bool


# --- Visualization ---------------------------------------------------------

class DatasetSummary(BaseModel):
    total_papers: int
    total_authors: int
    total_categories: int
    embedded_papers: int
    earliest_published: datetime | None
    latest_published: datetime | None


class TimeBucket(BaseModel):
    period: str
    paper_count: int


class CategoryCount(BaseModel):
    category: str
    paper_count: int
    primary_count: int


class AuthorCount(BaseModel):
    author: str
    paper_count: int


class AuthorsPerPaper(BaseModel):
    average: float
    median: float
    minimum: int
    maximum: int
    distribution: list[dict]


class CategorySeries(BaseModel):
    category: str
    points: list[TimeBucket]


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
