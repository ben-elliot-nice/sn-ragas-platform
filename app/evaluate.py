"""Orchestrates the /evaluate pipeline (spec 6.3).

    1. Validate auth and payload      -> done by caller (function_app.py)
    2. Classify the response          -> classification.py
    3. Match reference                -> matching.py (always runs)
    4. Select + run metrics           -> outcomes.decide_case + metrics.py
    5. Apply thresholds               -> outcomes.compute_outcomes
    6. Deterministic retrieval check  -> retrieval_check.py
    7. Log full detail                -> result_log.py
    8. Return response                -> schemas.EvaluateResponse
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from ragas import __version__ as RAGAS_VERSION
from ragas.dataset_schema import SingleTurnSample

from .classification import classify_response
from .golden_set import GoldenSet
from .matching import match_reference
from .metrics import build_sample, run_selected_metrics
from .outcomes import compute_outcomes, decide_case, error_outcomes
from .result_log import ResultLog
from .retrieval_check import compute_retrieval_check
from .schemas import EvaluateRequest, EvaluateResponse, MatchOut, OutcomesOut, ScoresOut


@dataclass
class EvaluationDeps:
    chat_model: object
    embed_query: Callable
    golden_set: GoldenSet
    metrics_by_name: Dict[str, object]
    thresholds: Dict[str, float]
    confidence_floor: float
    result_log: ResultLog
    judge_model_name: str
    golden_set_version: str
    metric_timeout: Optional[float] = None


async def evaluate(request: EvaluateRequest, deps: EvaluationDeps) -> EvaluateResponse:
    eval_id = str(uuid.uuid4())
    timings: Dict[str, float] = {}
    t0 = time.monotonic()

    def _mark(name: str, since: float) -> float:
        now = time.monotonic()
        timings[name] = round(now - since, 3)
        return now

    t = t0
    classification_result = await classify_response(
        request.standalone_query or request.user_message, request.response, deps.chat_model
    )
    t = _mark("classify", t)

    match = await match_reference(
        standalone_query=request.standalone_query,
        user_message=request.user_message,
        recent_turns=request.recent_turns,
        golden_set=deps.golden_set,
        chat_model=deps.chat_model,
        embed_query=deps.embed_query,
        confidence_floor=deps.confidence_floor,
    )
    t = _mark("match", t)

    matched_entry = deps.golden_set.get(match.reference_id) if match.reference_id else None
    decision = decide_case(
        classification=classification_result.label,
        matched=matched_entry is not None,
        expected_classification=match.expected_classification,
    )

    raw_scores: Dict[str, float] = {}
    if decision.metrics_to_run:
        sample = build_sample(
            user_input=request.standalone_query or request.user_message,
            response=request.response,
            retrieved_context_texts=[c.text for c in request.retrieved_contexts],
            reference=matched_entry.reference_answer if matched_entry else None,
        )
        raw_scores = await run_selected_metrics(
            decision.metrics_to_run, sample, deps.metrics_by_name, timeout=deps.metric_timeout
        )
    t = _mark("metrics", t)

    outcomes = compute_outcomes(decision.case, raw_scores, deps.thresholds)

    retrieval_check = compute_retrieval_check(
        matched_entry, [c.chunk_id for c in request.retrieved_contexts]
    )

    response = EvaluateResponse(
        eval_id=eval_id,
        golden_set_version=deps.golden_set_version,
        classification=classification_result.label,
        match=match,
        scores=ScoresOut(**{k: raw_scores.get(k) for k in ScoresOut.model_fields}),
        outcomes=OutcomesOut(**outcomes),
        retrieval_check=retrieval_check,
        ragas_version=RAGAS_VERSION,
        judge_model=deps.judge_model_name,
    )
    _mark("total", t0)

    deps.result_log.write(
        {
            "eval_id": eval_id,
            "session_id": request.session_id,
            "input_id": request.input_id,
            "run_id": request.run_id,
            "request": request.model_dump(),
            "classification": classification_result.label,
            "classification_reason": classification_result.reason,
            "case": decision.case,
            "metrics_run": decision.metrics_to_run,
            "match": match.model_dump(),
            "scores": raw_scores,
            "outcomes": outcomes,
            "retrieval_check": retrieval_check.model_dump(),
            "golden_set_version": deps.golden_set_version,
            "ragas_version": RAGAS_VERSION,
            "judge_model": deps.judge_model_name,
            "timings": timings,
        }
    )

    return response


def error_result_log_record(eval_id: str, request: Optional[dict], error_code: str, message: str) -> dict:
    return {
        "eval_id": eval_id,
        "request": request,
        "error": error_code,
        "message": message,
        "outcomes": error_outcomes(),
    }
