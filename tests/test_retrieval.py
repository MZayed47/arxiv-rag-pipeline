from app.services import retrieval


def make_candidate(paper_id, vector_similarity=0.0, keyword_rank=0.0):
    return retrieval.Candidate(
        paper_id=paper_id,
        arxiv_id=f"2401.{paper_id:05d}",
        title=f"Paper {paper_id}",
        abstract="abstract",
        primary_category="cs.AI",
        published_at=None,
        doi=None,
        journal_ref=None,
        vector_similarity=vector_similarity,
        keyword_rank=keyword_rank,
    )


def test_fuse_deduplicates_and_ranks_overlap_first():
    vector_hits = [make_candidate(1, 0.9), make_candidate(2, 0.8)]
    keyword_hits = [make_candidate(2, keyword_rank=0.5), make_candidate(3, keyword_rank=0.4)]

    fused = retrieval.fuse(vector_hits, keyword_hits)

    assert len(fused) == 3
    assert fused[0].paper_id == 2  # present in both lists
    assert fused[0].keyword_rank == 0.5
    assert fused[0].vector_similarity == 0.8


def test_fuse_keeps_keyword_only_hits():
    fused = retrieval.fuse([], [make_candidate(7, keyword_rank=0.9)])

    assert [c.paper_id for c in fused] == [7]


def test_is_weak_match_on_empty_result():
    assert retrieval.is_weak_match([]) is True


def test_is_weak_match_when_similarity_below_threshold():
    weak = [make_candidate(1, vector_similarity=retrieval.RAG_MIN_SIMILARITY - 0.1)]

    assert retrieval.is_weak_match(weak) is True


def test_keyword_hit_rescues_a_low_similarity_match():
    candidates = [
        make_candidate(1, vector_similarity=0.05, keyword_rank=0.7),
    ]

    assert retrieval.is_weak_match(candidates) is False


def test_candidate_url_points_to_arxiv():
    assert make_candidate(1).url == "https://arxiv.org/abs/2401.00001"
