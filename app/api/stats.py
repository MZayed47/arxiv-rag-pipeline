"""Visualization API — aggregated views computed from the database."""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from app.models import (
    AuthorCount,
    AuthorsPerPaper,
    CategoryCount,
    CategorySeries,
    DatasetSummary,
    TimeBucket,
)
from app.services import aggregations

router = APIRouter(prefix="/stats", tags=["visualization"])


@router.get("/summary", response_model=DatasetSummary)
def get_summary():
    return aggregations.summary()


@router.get("/papers-over-time", response_model=list[TimeBucket])
def get_papers_over_time(
    granularity: str = Query("month", pattern="^(day|month|year)$"),
    category: str | None = Query(None, max_length=32),
    start: datetime | None = None,
    end: datetime | None = None,
):
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="start must be before end")
    return aggregations.papers_over_time(granularity, category, start, end)


@router.get("/top-categories", response_model=list[CategoryCount])
def get_top_categories(limit: int = Query(10, ge=1, le=100)):
    return aggregations.top_categories(limit)


@router.get("/top-authors", response_model=list[AuthorCount])
def get_top_authors(limit: int = Query(10, ge=1, le=100)):
    return aggregations.top_authors(limit)


@router.get("/authors-per-paper", response_model=AuthorsPerPaper)
def get_authors_per_paper():
    return aggregations.authors_per_paper()


@router.get("/category-trends", response_model=list[CategorySeries])
def get_category_trends(
    limit: int = Query(5, ge=1, le=20),
    granularity: str = Query("month", pattern="^(day|month|year)$"),
):
    return aggregations.category_trends(limit, granularity)
