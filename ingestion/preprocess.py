"""
Atom/XML parsing and normalization.

Turns a raw arXiv <entry> element into a PaperRecord with clean text, timezone
aware dates, flattened authors/categories and two hashes:

    content_hash  — everything that makes a paper "changed" (drives upserts)
    source_hash   — title + abstract only (drives re-embedding)
"""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"
OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"

NS = {"atom": ATOM_NS, "arxiv": ARXIV_NS, "opensearch": OPENSEARCH_NS}

_WHITESPACE = re.compile(r"\s+")
_LATEX_INLINE = re.compile(r"\$([^$]{1,80})\$")
_VERSION_SUFFIX = re.compile(r"v\d+$")


@dataclass
class PaperRecord:
    arxiv_id: str
    title: str
    abstract: str
    authors: list[str]
    categories: list[str]
    primary_category: str | None
    published_at: datetime
    updated_at: datetime
    doi: str | None = None
    journal_ref: str | None = None
    content_hash: str = ""
    source_hash: str = ""

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = compute_content_hash(self)
        if not self.source_hash:
            self.source_hash = compute_source_hash(self.title, self.abstract)


def clean_text(value: str | None) -> str:
    """Collapse the line wrapping arXiv puts in titles and abstracts."""
    if not value:
        return ""
    text = _WHITESPACE.sub(" ", value).strip()
    text = text.replace("\\'", "'").replace("\\\"", '"')
    text = _LATEX_INLINE.sub(r"\1", text)
    return text.strip()


def _element_text(element) -> str | None:
    if element is None:
        return None
    return clean_text(element.text) or None


def normalize_arxiv_id(raw_id: str) -> str:
    """http://arxiv.org/abs/2301.12345v2 -> 2301.12345"""
    arxiv_id = (raw_id or "").strip()
    if "/abs/" in arxiv_id:
        arxiv_id = arxiv_id.split("/abs/", 1)[1]
    return _VERSION_SUFFIX.sub("", arxiv_id)


def normalize_author(name: str) -> str:
    """Case- and spacing-insensitive key used to deduplicate author rows."""
    return _WHITESPACE.sub(" ", (name or "").strip()).lower()


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def compute_content_hash(record: "PaperRecord") -> str:
    payload = "|".join([
        record.arxiv_id,
        record.title,
        record.abstract,
        record.updated_at.isoformat() if record.updated_at else "",
        record.doi or "",
        record.journal_ref or "",
        ",".join(record.authors),
        ",".join(sorted(record.categories)),
    ])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def compute_source_hash(title: str, abstract: str) -> str:
    return hashlib.sha1(f"{title}\n\n{abstract}".encode("utf-8")).hexdigest()


def parse_entry(entry: ET.Element) -> PaperRecord | None:
    """Convert one Atom <entry> into a PaperRecord, or None if unusable."""
    arxiv_id = normalize_arxiv_id(_element_text(entry.find("atom:id", NS)) or "")
    title = clean_text(_element_text(entry.find("atom:title", NS)))
    if not arxiv_id or not title:
        return None

    abstract = clean_text(_element_text(entry.find("atom:summary", NS)))

    published = parse_datetime(_element_text(entry.find("atom:published", NS)))
    updated = parse_datetime(_element_text(entry.find("atom:updated", NS)))
    if published is None and updated is None:
        return None
    published = published or updated
    updated = updated or published

    authors: list[str] = []
    for author in entry.findall("atom:author", NS):
        name = _element_text(author.find("atom:name", NS))
        if name and name not in authors:
            authors.append(name)

    categories: list[str] = []
    for category in entry.findall("atom:category", NS):
        term = category.attrib.get("term")
        if term and term not in categories:
            categories.append(term)

    primary_element = entry.find("arxiv:primary_category", NS)
    primary_category = primary_element.attrib.get("term") if primary_element is not None else None
    if primary_category and primary_category not in categories:
        categories.insert(0, primary_category)

    return PaperRecord(
        arxiv_id=arxiv_id,
        title=title,
        abstract=abstract,
        authors=authors,
        categories=categories,
        primary_category=primary_category,
        published_at=published,
        updated_at=updated,
        doi=_element_text(entry.find("arxiv:doi", NS)),
        journal_ref=_element_text(entry.find("arxiv:journal_ref", NS)),
    )


def parse_feed(xml_bytes: bytes) -> tuple[list[PaperRecord], int]:
    """Parse a full Atom response into (records, total_results)."""
    root = ET.fromstring(xml_bytes)

    total_element = root.find("opensearch:totalResults", NS)
    total_results = int(total_element.text or "0") if total_element is not None else 0

    records = []
    for entry in root.findall("atom:entry", NS):
        record = parse_entry(entry)
        if record is not None:
            records.append(record)

    return records, total_results
