"""Deterministic retrieval check (spec 6.3 step 6). Independent of the Ragas
outcome logic: reported alongside the scores whenever there's a matched
golden entry, regardless of which case outcomes.py selected.
"""
from __future__ import annotations

from typing import List, Optional

from .golden_set import GoldenEntry
from .schemas import RetrievalCheckOut


def compute_retrieval_check(
    matched_entry: Optional[GoldenEntry],
    retrieved_chunk_ids: List[str],
) -> RetrievalCheckOut:
    if matched_entry is None:
        return RetrievalCheckOut(expected_chunk_ids=[], retrieved_expected=0)

    expected = matched_entry.source_chunk_ids
    retrieved_set = set(retrieved_chunk_ids)
    retrieved_expected = sum(1 for c in expected if c in retrieved_set)
    return RetrievalCheckOut(expected_chunk_ids=expected, retrieved_expected=retrieved_expected)
