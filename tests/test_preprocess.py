from datetime import timezone

from ingestion import preprocess


def test_parse_feed_extracts_all_fields(sample_feed):
    records, total = preprocess.parse_feed(sample_feed)

    assert total == 2
    assert len(records) == 2

    paper = records[0]
    assert paper.arxiv_id == "2401.12345"
    assert paper.title == "Retrieval Augmented Generation for Scientific Abstracts"
    assert paper.authors == ["Ada Lovelace", "Alan Turing"]
    assert paper.primary_category == "cs.IR"
    assert set(paper.categories) == {"cs.IR", "cs.CL"}
    assert paper.doi == "10.1000/test.2024.1"
    assert paper.journal_ref == "Journal of Tests, 12(3), 2024"


def test_missing_doi_and_journal_ref_become_none(sample_feed):
    records, _ = preprocess.parse_feed(sample_feed)
    paper = records[1]

    assert paper.doi is None
    assert paper.journal_ref is None


def test_abstract_is_cleaned(sample_feed):
    records, _ = preprocess.parse_feed(sample_feed)
    abstract = records[0].abstract

    assert "\n" not in abstract
    assert "  " not in abstract
    assert "$" not in abstract
    assert abstract.startswith("We present a system")


def test_dates_are_normalized_to_utc(sample_feed):
    records, _ = preprocess.parse_feed(sample_feed)
    paper = records[0]

    assert paper.published_at.tzinfo == timezone.utc
    assert paper.published_at.isoformat() == "2024-01-15T12:00:00+00:00"
    assert paper.updated_at.isoformat() == "2024-02-01T10:00:00+00:00"


def test_version_suffix_is_stripped():
    assert preprocess.normalize_arxiv_id("http://arxiv.org/abs/2301.09876v12") == "2301.09876"
    assert preprocess.normalize_arxiv_id("2301.09876") == "2301.09876"


def test_author_normalization_is_case_and_space_insensitive():
    assert preprocess.normalize_author("  Ada   LOVELACE ") == "ada lovelace"


def test_content_hash_changes_with_content(sample_feed):
    records, _ = preprocess.parse_feed(sample_feed)
    original = records[0]

    same = preprocess.PaperRecord(
        arxiv_id=original.arxiv_id,
        title=original.title,
        abstract=original.abstract,
        authors=list(original.authors),
        categories=list(original.categories),
        primary_category=original.primary_category,
        published_at=original.published_at,
        updated_at=original.updated_at,
        doi=original.doi,
        journal_ref=original.journal_ref,
    )
    assert same.content_hash == original.content_hash

    changed = preprocess.PaperRecord(
        arxiv_id=original.arxiv_id,
        title=original.title,
        abstract=original.abstract + " Revised.",
        authors=list(original.authors),
        categories=list(original.categories),
        primary_category=original.primary_category,
        published_at=original.published_at,
        updated_at=original.updated_at,
    )
    assert changed.content_hash != original.content_hash
    assert changed.source_hash != original.source_hash
