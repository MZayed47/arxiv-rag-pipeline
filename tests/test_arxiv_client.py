import pytest

from ingestion.arxiv_client import ArxivClient, ArxivError


class FakeResponse:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        return self.responses.pop(0)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("ingestion.arxiv_client.time.sleep", lambda _s: None)
    instance = ArxivClient(delay=0, batch_size=2)
    return instance


def test_fetch_page_parses_records(client, sample_feed):
    client.session = FakeSession([FakeResponse(200, sample_feed)])

    records, total = client.fetch_page("cs.IR", start=0, max_results=2)

    assert total == 2
    assert [r.arxiv_id for r in records] == ["2401.12345", "2402.00001"]
    assert client.session.calls[0]["search_query"] == "cat:cs.IR"
    assert client.session.calls[0]["sortBy"] == "submittedDate"


def test_fetch_page_retries_on_throttling(client, sample_feed):
    client.session = FakeSession([FakeResponse(503), FakeResponse(200, sample_feed)])

    records, _ = client.fetch_page("cs.IR", start=0, max_results=2)

    assert len(records) == 2
    assert len(client.session.calls) == 2


def test_fetch_page_gives_up_after_max_retries(client, monkeypatch):
    monkeypatch.setattr("ingestion.arxiv_client.ARXIV_MAX_RETRIES", 2)
    client.session = FakeSession([FakeResponse(503), FakeResponse(503)])

    with pytest.raises(ArxivError):
        client.fetch_page("cs.IR", start=0, max_results=2)


def test_iter_category_filters_cross_listed_papers(client, sample_feed):
    client.session = FakeSession([FakeResponse(200, sample_feed)])

    papers = list(client.iter_category("cs.IR", target_count=5, primary_only=True))

    # Only the first entry has cs.IR as its primary category.
    assert [p.arxiv_id for p in papers] == ["2401.12345"]


def test_fetch_page_rejects_unknown_sort_field(client):
    with pytest.raises(ValueError):
        client.fetch_page("cs.IR", start=0, max_results=2, sort_by="relevance")
