"""Request/response schemas for POST /evaluate. Mirrors build spec section 6.2 exactly."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Classification = Literal["ANSWER", "CLARIFY", "DECLINE"]
OutcomeValue = Literal["pass", "fail", "unverified", "not_scored", "skipped", "error"]


class Turn(BaseModel):
    role: str
    text: str


class RetrievedContext(BaseModel):
    chunk_id: str
    source_id: str
    text: str
    rank: int


class EvaluateRequest(BaseModel):
    session_id: str
    input_id: str
    run_id: str
    user_message: str
    standalone_query: str = ""
    recent_turns: List[Turn] = Field(default_factory=list)
    response: str
    retrieved_contexts: List[RetrievedContext] = Field(default_factory=list)


class MatchOut(BaseModel):
    reference_id: Optional[str]
    confidence: float
    expected_classification: Optional[Classification]
    candidates: List[str]


class ScoresOut(BaseModel):
    faithfulness: Optional[float] = None
    factual_correctness: Optional[float] = None
    response_relevancy: Optional[float] = None
    context_recall: Optional[float] = None
    context_precision: Optional[float] = None


class OutcomesOut(BaseModel):
    accurate: OutcomeValue
    retrieval: OutcomeValue
    relevant: OutcomeValue


class RetrievalCheckOut(BaseModel):
    expected_chunk_ids: List[str]
    retrieved_expected: int


class EvaluateResponse(BaseModel):
    eval_id: str
    golden_set_version: str
    classification: Classification
    match: MatchOut
    scores: ScoresOut
    outcomes: OutcomesOut
    retrieval_check: RetrievalCheckOut
    ragas_version: str
    judge_model: str


class ErrorResponse(BaseModel):
    error: str
    message: str
    eval_id: str
