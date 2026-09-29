"""Reference matching against the golden set (spec 6.5).

Runs for every classification, since CLARIFY and DECLINE outcomes depend on
the matched entry's expected_classification. The golden set never leaves
this service: only reference_id, confidence, expected_classification and the
candidate id list cross the API boundary.
"""
from __future__ import annotations

import math
from typing import List, Optional

from pydantic import BaseModel, Field

from .golden_set import GoldenEntry, GoldenSet
from .schemas import MatchOut, Turn

SHORTLIST_SIZE = 5

REWRITE_SYSTEM_PROMPT = """Rewrite the user's latest message as a standalone question that
makes sense without the prior conversation. Resolve pronouns and implicit references
using the recent turns. Return only the rewritten question, no commentary."""

MATCH_SYSTEM_PROMPT = """You match a customer's question against a shortlist of candidate
reference questions from a knowledge base FAQ set. Pick the single best match, or "none"
if none of the candidates are asking the same thing. Near-duplicate topics that differ in
a key detail (a different plan name, a different condition) are NOT the same question —
return "none" for those rather than the closest-sounding candidate.

Return the candidate id you picked (or the literal string "none") and your confidence
from 0.0 to 1.0."""


class MatchJudgeOutput(BaseModel):
    reference_id: str = Field(description='A candidate id from the shortlist, or the literal string "none"')
    confidence: float = Field(ge=0.0, le=1.0)


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def best_similarity(query_vec: List[float], entry: GoldenEntry) -> float:
    return max(_cosine(query_vec, v) for v in entry.question_vectors)


def shortlist_entries(query_vec: List[float], golden_set: GoldenSet, k: int = SHORTLIST_SIZE) -> List[GoldenEntry]:
    scored = [(best_similarity(query_vec, e), e) for e in golden_set.entries if e.question_vectors]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [e for _, e in scored[:k]]


async def rewrite_standalone_query(user_message: str, recent_turns: List[Turn], chat_model) -> str:
    history = "\n".join(f"{t.role}: {t.text}" for t in recent_turns)
    result = await chat_model.ainvoke(
        [
            ("system", REWRITE_SYSTEM_PROMPT),
            ("user", f"Recent turns:\n{history}\n\nLatest message: {user_message}"),
        ]
    )
    text = result.content if hasattr(result, "content") else str(result)
    return text.strip()


async def judge_pick_match(query: str, shortlist: List[GoldenEntry], chat_model) -> MatchJudgeOutput:
    candidates_block = "\n".join(f"- {e.id}: {e.canonical_question}" for e in shortlist)
    structured_model = chat_model.with_structured_output(MatchJudgeOutput)
    return await structured_model.ainvoke(
        [
            ("system", MATCH_SYSTEM_PROMPT),
            ("user", f"Customer question: {query}\n\nCandidates:\n{candidates_block}"),
        ]
    )


async def match_reference(
    *,
    standalone_query: str,
    user_message: str,
    recent_turns: List[Turn],
    golden_set: GoldenSet,
    chat_model,
    embed_query,
    confidence_floor: float,
) -> MatchOut:
    query = (standalone_query or "").strip()
    if not query:
        query = await rewrite_standalone_query(user_message, recent_turns, chat_model)

    query_vec = await embed_query(query)
    shortlist = shortlist_entries(query_vec, golden_set)

    if not shortlist:
        return MatchOut(reference_id=None, confidence=0.0, expected_classification=None, candidates=[])

    candidates = [e.id for e in shortlist]
    pick = await judge_pick_match(query, shortlist, chat_model)

    matched: Optional[GoldenEntry] = None
    if pick.reference_id != "none" and pick.confidence >= confidence_floor:
        matched = next((e for e in shortlist if e.id == pick.reference_id), None)

    return MatchOut(
        reference_id=matched.id if matched else None,
        confidence=pick.confidence,
        expected_classification=matched.expected_classification if matched else None,
        candidates=candidates,
    )
