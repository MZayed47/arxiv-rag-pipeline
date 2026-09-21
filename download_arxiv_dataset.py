#!/usr/bin/env python3

"""
Standalone snapshot tool — writes the arXiv dataset to data/*.json(l) without
touching the database. Useful for inspecting the raw feed or for working
offline. The database path is `python -m ingestion.run_ingestion ingest`,
which reuses the same fetching and parsing logic via ingestion/arxiv_client.py.

Download 1,000 arXiv papers from 5 categories.

Default:
    200 papers per category
    5 categories
    = 1,000 unique papers total

Source:
    https://export.arxiv.org/api/query

Output:
    data/arxiv_1000.json
    data/arxiv_1000.jsonl

JSON structure per paper:

{
    "arxiv_id": "2301.12345",
    "title": "...",
    "authors": ["Author One", "Author Two"],
    "primary_category": "cs.AI",
    "categories": ["cs.AI", "cs.LG"],
    "published": "2023-01-15T12:00:00Z",
    "updated": "2023-02-01T10:00:00Z",
    "doi": "10.xxxx/xxxxx",
    "journal_ref": "...",
    "abstract": "..."
}
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

import requests


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_URL = "https://export.arxiv.org/api/query"

CATEGORIES = [
    "cs.AI",
    "cs.LG",
    "cs.CL",
    "cs.CV",
    "cs.IR",
]

PAPERS_PER_CATEGORY = 200
BATCH_SIZE = 200

OUTPUT_DIR = Path("data")
JSON_OUTPUT = OUTPUT_DIR / "arxiv_1000.json"
JSONL_OUTPUT = OUTPUT_DIR / "arxiv_1000.jsonl"

# arXiv requests should not be sent aggressively.
REQUEST_DELAY_SECONDS = 3.0

REQUEST_TIMEOUT_SECONDS = 60

MAX_RETRIES = 5

USER_AGENT = (
    "ArxivDatasetCollector/1.0 "
    "(research dataset collection; contact: your-email@example.com)"
)


# ---------------------------------------------------------------------------
# XML namespaces
# ---------------------------------------------------------------------------

ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"
OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"

NS = {
    "atom": ATOM_NS,
    "arxiv": ARXIV_NS,
    "opensearch": OPENSEARCH_NS,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_text(value: Optional[str]) -> str:
    """Normalize whitespace in XML text."""
    if not value:
        return ""

    return re.sub(r"\s+", " ", value).strip()


def get_text(element: Optional[ET.Element]) -> Optional[str]:
    """Extract and normalize element text."""
    if element is None:
        return None

    return clean_text(element.text)


def normalize_arxiv_id(raw_id: str) -> str:
    """
    Convert:

        http://arxiv.org/abs/2301.12345v2

    into:

        2301.12345
    """
    arxiv_id = raw_id.strip()

    if "/abs/" in arxiv_id:
        arxiv_id = arxiv_id.split("/abs/", 1)[1]

    # Remove version suffix, e.g. v1, v2, v3
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id)

    return arxiv_id


def parse_entry(entry: ET.Element) -> Dict:
    """Convert a single Atom <entry> into a Python dictionary."""

    raw_id = get_text(entry.find("atom:id", NS)) or ""

    title = get_text(entry.find("atom:title", NS)) or ""

    abstract = get_text(entry.find("atom:summary", NS)) or ""

    published = get_text(entry.find("atom:published", NS))

    updated = get_text(entry.find("atom:updated", NS))

    # -----------------------------------------------------------------------
    # Authors
    # -----------------------------------------------------------------------

    authors: List[str] = []

    for author in entry.findall("atom:author", NS):
        name = get_text(author.find("atom:name", NS))

        if name:
            authors.append(name)

    # -----------------------------------------------------------------------
    # Categories
    # -----------------------------------------------------------------------

    categories: List[str] = []

    for category in entry.findall("atom:category", NS):
        term = category.attrib.get("term")

        if term:
            categories.append(term)

    # Remove duplicates while preserving order
    categories = list(dict.fromkeys(categories))

    # -----------------------------------------------------------------------
    # Primary category
    # -----------------------------------------------------------------------

    primary_category_element = entry.find(
        "arxiv:primary_category",
        NS,
    )

    primary_category = None

    if primary_category_element is not None:
        primary_category = primary_category_element.attrib.get("term")

    # -----------------------------------------------------------------------
    # Optional metadata
    # -----------------------------------------------------------------------

    doi_element = entry.find("arxiv:doi", NS)

    journal_ref_element = entry.find(
        "arxiv:journal_ref",
        NS,
    )

    doi = get_text(doi_element)

    journal_ref = get_text(journal_ref_element)

    # -----------------------------------------------------------------------
    # Result
    # -----------------------------------------------------------------------

    return {
        "arxiv_id": normalize_arxiv_id(raw_id),
        "title": title,
        "authors": authors,
        "primary_category": primary_category,
        "categories": categories,
        "published": published,
        "updated": updated,
        "doi": doi,
        "journal_ref": journal_ref,
        "abstract": abstract,
    }


def fetch_page(
    session: requests.Session,
    category: str,
    start: int,
    max_results: int,
) -> tuple[List[Dict], int]:
    """
    Fetch one page from the arXiv API.

    Returns:
        records, total_results
    """

    params = {
        "search_query": f"cat:{category}",
        "start": start,
        "max_results": max_results,

        # Most recent submissions first.
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            response = session.get(
                API_URL,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

            # Retry temporary server/client throttling responses.
            if response.status_code in (429, 500, 502, 503, 504):

                if attempt == MAX_RETRIES:
                    response.raise_for_status()

                wait_seconds = min(
                    60,
                    2 ** (attempt - 1) * 5,
                )

                print(
                    f"Temporary HTTP {response.status_code}. "
                    f"Retrying in {wait_seconds}s..."
                )

                time.sleep(wait_seconds)
                continue

            response.raise_for_status()

            root = ET.fromstring(response.content)

            # Check for API error returned inside Atom XML.
            error_entry = root.find("atom:entry", NS)

            if error_entry is not None:
                error_summary = get_text(
                    error_entry.find("atom:summary", NS)
                )

                if error_summary:
                    raise RuntimeError(
                        f"arXiv API error: {error_summary}"
                    )

            entries = root.findall("atom:entry", NS)

            total_results_element = root.find(
                "opensearch:totalResults",
                NS,
            )

            total_results = 0

            if total_results_element is not None:
                total_results = int(
                    total_results_element.text or "0"
                )

            records = [
                parse_entry(entry)
                for entry in entries
            ]

            return records, total_results

        except (
            requests.RequestException,
            ET.ParseError,
            ValueError,
        ) as exc:

            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"Failed fetching {category} "
                    f"start={start}: {exc}"
                ) from exc

            wait_seconds = min(
                60,
                2 ** (attempt - 1) * 5,
            )

            print(
                f"Request/parsing error: {exc}. "
                f"Retrying in {wait_seconds}s..."
            )

            time.sleep(wait_seconds)

    raise RuntimeError("Unexpected fetch_page failure")


def collect_category(
    session: requests.Session,
    category: str,
    target_count: int,
    global_ids: set[str],
) -> List[Dict]:
    """
    Collect exactly target_count papers whose primary category is the
    requested category.

    Filtering by primary_category prevents the same paper from being
    counted toward multiple category quotas.
    """

    collected: List[Dict] = []

    start = 0

    while len(collected) < target_count:

        remaining = target_count - len(collected)

        batch_size = min(
            BATCH_SIZE,
            max(remaining * 2, BATCH_SIZE),
        )

        print(
            f"[{category}] Requesting "
            f"start={start}, max_results={batch_size}"
        )

        records, total_results = fetch_page(
            session=session,
            category=category,
            start=start,
            max_results=batch_size,
        )

        if not records:
            print(
                f"[{category}] No more results available."
            )
            break

        # The API's start index refers to the full search result set.
        start += len(records)

        for record in records:

            arxiv_id = record["arxiv_id"]

            # Keep only papers whose PRIMARY category matches.
            if record["primary_category"] != category:
                continue

            # Global deduplication.
            if arxiv_id in global_ids:
                continue

            global_ids.add(arxiv_id)
            collected.append(record)

            if len(collected) >= target_count:
                break

        print(
            f"[{category}] Collected "
            f"{len(collected)}/{target_count} "
            f"primary-category papers"
        )

        if start >= total_results:
            break

        # arXiv asks clients to wait between consecutive requests.
        time.sleep(REQUEST_DELAY_SECONDS)

    if len(collected) < target_count:
        raise RuntimeError(
            f"Could only collect {len(collected)} papers for "
            f"{category}, but {target_count} were requested."
        )

    return collected


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:

    total_target = len(CATEGORIES) * PAPERS_PER_CATEGORY

    print("=" * 72)
    print("arXiv Dataset Collector")
    print("=" * 72)
    print(f"Categories: {', '.join(CATEGORIES)}")
    print(f"Papers per category: {PAPERS_PER_CATEGORY}")
    print(f"Target total: {total_target}")
    print(f"API: {API_URL}")
    print("=" * 72)

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/atom+xml",
        }
    )

    all_papers: List[Dict] = []

    global_ids: set[str] = set()

    # -----------------------------------------------------------------------
    # Collect each category independently.
    # -----------------------------------------------------------------------

    for index, category in enumerate(CATEGORIES, start=1):

        print()
        print(
            f"--- Category {index}/{len(CATEGORIES)}: "
            f"{category} ---"
        )

        papers = collect_category(
            session=session,
            category=category,
            target_count=PAPERS_PER_CATEGORY,
            global_ids=global_ids,
        )

        all_papers.extend(papers)

        print(
            f"Finished {category}: "
            f"{len(papers)} papers"
        )

        # Respect arXiv API pacing between category requests.
        if index < len(CATEGORIES):
            time.sleep(REQUEST_DELAY_SECONDS)

    # -----------------------------------------------------------------------
    # Safety check.
    # -----------------------------------------------------------------------

    if len(all_papers) < total_target:
        raise RuntimeError(
            f"Dataset contains only {len(all_papers)} papers; "
            f"expected {total_target}."
        )

    if len({paper["arxiv_id"] for paper in all_papers}) != len(all_papers):
        raise RuntimeError(
            "Duplicate arXiv IDs detected."
        )

    # -----------------------------------------------------------------------
    # Write JSON.
    # -----------------------------------------------------------------------

    with JSON_OUTPUT.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            all_papers,
            f,
            ensure_ascii=False,
            indent=2,
        )

    # -----------------------------------------------------------------------
    # Write JSONL.
    #
    # JSONL is especially useful for RAG pipelines because each paper is
    # an independent document.
    # -----------------------------------------------------------------------

    with JSONL_OUTPUT.open(
        "w",
        encoding="utf-8",
    ) as f:

        for paper in all_papers:

            f.write(
                json.dumps(
                    paper,
                    ensure_ascii=False,
                )
                + "\n"
            )

    # -----------------------------------------------------------------------
    # Print summary.
    # -----------------------------------------------------------------------

    print()
    print("=" * 72)
    print("DOWNLOAD COMPLETE")
    print("=" * 72)

    print(f"Total papers: {len(all_papers)}")

    for category in CATEGORIES:

        count = sum(
            1
            for paper in all_papers
            if paper["primary_category"] == category
        )

        print(
            f"{category}: {count}"
        )

    doi_count = sum(
        1
        for paper in all_papers
        if paper["doi"]
    )

    journal_ref_count = sum(
        1
        for paper in all_papers
        if paper["journal_ref"]
    )

    print()
    print(f"Papers with DOI: {doi_count}")
    print(f"Papers with journal reference: {journal_ref_count}")

    print()
    print(f"JSON : {JSON_OUTPUT}")
    print(f"JSONL: {JSONL_OUTPUT}")


if __name__ == "__main__":
    main()
