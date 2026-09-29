from app.golden_set import GoldenEntry
from app.retrieval_check import compute_retrieval_check


def make_entry(source_chunk_ids):
    return GoldenEntry(
        id="FAQ-X",
        category="Travel",
        test_type="single_fact",
        canonical_question="q",
        question_variants=[],
        reference_answer="a",
        source_article_ids=[],
        source_chunk_ids=source_chunk_ids,
        expected_classification="ANSWER",
    )


def test_no_match_returns_empty():
    result = compute_retrieval_check(None, ["KB-TRV-003-01"])
    assert result.expected_chunk_ids == []
    assert result.retrieved_expected == 0


def test_full_overlap():
    entry = make_entry(["KB-TRV-003-01", "KB-TRV-002-01"])
    result = compute_retrieval_check(entry, ["KB-TRV-002-01", "KB-TRV-003-01", "KB-GEN-001-01"])
    assert result.expected_chunk_ids == ["KB-TRV-003-01", "KB-TRV-002-01"]
    assert result.retrieved_expected == 2


def test_partial_overlap():
    entry = make_entry(["KB-TRV-003-01", "KB-TRV-002-01"])
    result = compute_retrieval_check(entry, ["KB-TRV-003-01"])
    assert result.retrieved_expected == 1


def test_no_expected_chunks():
    entry = make_entry([])
    result = compute_retrieval_check(entry, ["KB-TRV-003-01"])
    assert result.expected_chunk_ids == []
    assert result.retrieved_expected == 0
