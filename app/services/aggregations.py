"""
Visualization aggregations. Every figure is computed in Postgres from the
ingested tables — nothing here re-reads the arXiv API.
"""
import logging
from datetime import datetime

from app.db.pool import pool

log = logging.getLogger(__name__)

# Whitelisted so the granularity can be interpolated into date_trunc safely.
GRANULARITIES = {
    "day": ("day", "YYYY-MM-DD"),
    "month": ("month", "YYYY-MM"),
    "year": ("year", "YYYY"),
}


def summary() -> dict:
    sql = """
    SELECT
        (SELECT COUNT(*) FROM papers),
        (SELECT COUNT(*) FROM authors),
        (SELECT COUNT(*) FROM categories),
        (SELECT COUNT(*) FROM paper_embeddings),
        (SELECT MIN(published_at) FROM papers),
        (SELECT MAX(published_at) FROM papers)
    """
    with pool.connection() as conn:
        row = conn.execute(sql).fetchone()

    return {
        "total_papers": row[0],
        "total_authors": row[1],
        "total_categories": row[2],
        "embedded_papers": row[3],
        "earliest_published": row[4],
        "latest_published": row[5],
    }


def papers_over_time(
    granularity: str = "month",
    category: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict]:
    trunc, fmt = GRANULARITIES[granularity]

    joins = ""
    conditions = []
    params: list = [trunc, fmt]

    if category:
        joins = """
        JOIN paper_categories pc ON pc.paper_id = p.id
        JOIN categories c ON c.id = pc.category_id
        """
        conditions.append("c.code = %s")
        params.append(category)

    if start:
        conditions.append("p.published_at >= %s")
        params.append(start)
    if end:
        conditions.append("p.published_at < %s")
        params.append(end)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
    SELECT to_char(date_trunc(%s, p.published_at), %s) AS period,
           COUNT(DISTINCT p.id) AS paper_count
    FROM papers p
    {joins}
    {where}
    GROUP BY 1
    ORDER BY 1
    """
    with pool.connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [{"period": row[0], "paper_count": row[1]} for row in rows]


def top_categories(limit: int = 10) -> list[dict]:
    sql = """
    SELECT c.code,
           COUNT(*) AS paper_count,
           COUNT(*) FILTER (WHERE pc.is_primary) AS primary_count
    FROM paper_categories pc
    JOIN categories c ON c.id = pc.category_id
    GROUP BY c.code
    ORDER BY paper_count DESC, c.code
    LIMIT %s
    """
    with pool.connection() as conn:
        rows = conn.execute(sql, (limit,)).fetchall()

    return [
        {"category": row[0], "paper_count": row[1], "primary_count": row[2]}
        for row in rows
    ]


def top_authors(limit: int = 10) -> list[dict]:
    sql = """
    SELECT a.full_name, COUNT(*) AS paper_count
    FROM paper_authors pa
    JOIN authors a ON a.id = pa.author_id
    GROUP BY a.id, a.full_name
    ORDER BY paper_count DESC, a.full_name
    LIMIT %s
    """
    with pool.connection() as conn:
        rows = conn.execute(sql, (limit,)).fetchall()

    return [{"author": row[0], "paper_count": row[1]} for row in rows]


def authors_per_paper() -> dict:
    sql = """
    WITH counts AS (
        SELECT p.id, COUNT(pa.author_id) AS n
        FROM papers p
        LEFT JOIN paper_authors pa ON pa.paper_id = p.id
        GROUP BY p.id
    )
    SELECT
        COALESCE(ROUND(AVG(n)::numeric, 2), 0),
        COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY n), 0),
        COALESCE(MIN(n), 0),
        COALESCE(MAX(n), 0)
    FROM counts
    """
    distribution_sql = """
    WITH counts AS (
        SELECT p.id, COUNT(pa.author_id) AS n
        FROM papers p
        LEFT JOIN paper_authors pa ON pa.paper_id = p.id
        GROUP BY p.id
    )
    SELECT n, COUNT(*) FROM counts GROUP BY n ORDER BY n
    """
    with pool.connection() as conn:
        row = conn.execute(sql).fetchone()
        distribution = conn.execute(distribution_sql).fetchall()

    return {
        "average": float(row[0]),
        "median": float(row[1]),
        "minimum": int(row[2]),
        "maximum": int(row[3]),
        "distribution": [
            {"author_count": item[0], "paper_count": item[1]} for item in distribution
        ],
    }


def category_trends(limit: int = 5, granularity: str = "month") -> list[dict]:
    trunc, fmt = GRANULARITIES[granularity]
    sql = """
    WITH top AS (
        SELECT c.id, c.code
        FROM paper_categories pc
        JOIN categories c ON c.id = pc.category_id
        GROUP BY c.id, c.code
        ORDER BY COUNT(*) DESC
        LIMIT %s
    )
    SELECT top.code,
           to_char(date_trunc(%s, p.published_at), %s) AS period,
           COUNT(*) AS paper_count
    FROM papers p
    JOIN paper_categories pc ON pc.paper_id = p.id
    JOIN top ON top.id = pc.category_id
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    with pool.connection() as conn:
        rows = conn.execute(sql, (limit, trunc, fmt)).fetchall()

    series: dict[str, list] = {}
    for code, period, count in rows:
        series.setdefault(code, []).append({"period": period, "paper_count": count})

    return [{"category": code, "points": points} for code, points in series.items()]
