"""
arXiv API client: paginated fetching with self-throttling and retries.

arXiv asks for no more than one request every three seconds, so the client
sleeps between pages and backs off on 429/5xx responses.
"""
import logging
import time

import requests

from app.config import (
    ARXIV_API_URL,
    ARXIV_BATCH_SIZE,
    ARXIV_MAX_RETRIES,
    ARXIV_REQUEST_DELAY,
    ARXIV_TIMEOUT,
    ARXIV_USER_AGENT,
)
from ingestion.preprocess import PaperRecord, parse_feed

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}
SORT_FIELDS = {"submittedDate", "lastUpdatedDate"}


class ArxivError(RuntimeError):
    pass


class ArxivClient:
    def __init__(self, delay: float = ARXIV_REQUEST_DELAY, batch_size: int = ARXIV_BATCH_SIZE):
        self.delay = delay
        self.batch_size = batch_size
        self._last_request_at = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": ARXIV_USER_AGENT, "Accept": "application/atom+xml"}
        )

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if self._last_request_at and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request_at = time.monotonic()

    def fetch_page(
        self,
        category: str,
        start: int,
        max_results: int,
        sort_by: str = "submittedDate",
    ) -> tuple[list[PaperRecord], int]:
        if sort_by not in SORT_FIELDS:
            raise ValueError(f"sort_by must be one of {sorted(SORT_FIELDS)}")

        params = {
            "search_query": f"cat:{category}",
            "start": start,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": "descending",
        }

        for attempt in range(1, ARXIV_MAX_RETRIES + 1):
            self._throttle()
            try:
                response = self.session.get(
                    ARXIV_API_URL, params=params, timeout=ARXIV_TIMEOUT
                )

                if response.status_code in RETRY_STATUS:
                    if attempt == ARXIV_MAX_RETRIES:
                        raise ArxivError(
                            f"arXiv returned HTTP {response.status_code} after "
                            f"{ARXIV_MAX_RETRIES} attempts"
                        )
                    self._backoff(attempt, f"HTTP {response.status_code}")
                    continue

                response.raise_for_status()
                return parse_feed(response.content)

            except ArxivError:
                raise
            except Exception as exc:
                if attempt == ARXIV_MAX_RETRIES:
                    raise ArxivError(
                        f"Failed fetching {category} start={start}: {exc}"
                    ) from exc
                self._backoff(attempt, str(exc))

        raise ArxivError("unreachable")

    @staticmethod
    def _backoff(attempt: int, reason: str) -> None:
        wait = min(60, 5 * 2 ** (attempt - 1))
        log.warning("arXiv request failed (%s). Retrying in %ss", reason, wait)
        time.sleep(wait)

    def iter_category(
        self,
        category: str,
        target_count: int,
        sort_by: str = "submittedDate",
        primary_only: bool = True,
    ):
        """
        Yield up to target_count PaperRecords for a category.

        primary_only keeps a cross-listed paper from consuming the quota of
        several categories at once.
        """
        seen: set[str] = set()
        start = 0
        yielded = 0

        while yielded < target_count:
            records, total_results = self.fetch_page(
                category, start, self.batch_size, sort_by
            )
            if not records:
                log.info("[%s] no more results at start=%d", category, start)
                break

            start += len(records)

            for record in records:
                if record.arxiv_id in seen:
                    continue
                if primary_only and record.primary_category != category:
                    continue
                seen.add(record.arxiv_id)
                yielded += 1
                yield record
                if yielded >= target_count:
                    break

            log.info("[%s] %d/%d papers collected", category, yielded, target_count)

            if total_results and start >= total_results:
                break
