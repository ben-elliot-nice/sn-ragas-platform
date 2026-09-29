"""Outcome rules (spec 4.3). Pure logic, no LLM calls — decides which of the
five Ragas metrics to run for a given (classification, match) pair, and later
turns raw metric scores into pass/fail/unverified/not_scored/skipped outcomes.

The nine cases below are an exhaustive transcription of the table in section
4.3. Do not add a tenth case without updating the spec first.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

ALL_METRICS = [
    "faithfulness",
    "factual_correctness",
    "response_relevancy",
    "context_recall",
    "context_precision",
]
ANSWER_ONLY_METRICS = ["faithfulness", "response_relevancy"]


@dataclass(frozen=True)
class CaseDecision:
    case: str
    metrics_to_run: List[str]


def decide_case(
    classification: str,
    matched: bool,
    expected_classification: Optional[str],
) -> CaseDecision:
    if classification == "CLARIFY":
        if matched and expected_classification == "CLARIFY":
            return CaseDecision("clarify_matches_clarify", [])
        return CaseDecision("clarify_other", [])

    if classification == "ANSWER":
        if matched and expected_classification == "CLARIFY":
            return CaseDecision("answer_expects_clarify", ANSWER_ONLY_METRICS)
        if matched and expected_classification == "ANSWER":
            return CaseDecision("answer_matched_answer", ALL_METRICS)
        if matched and expected_classification == "DECLINE":
            return CaseDecision("answer_expects_decline", ANSWER_ONLY_METRICS)
        return CaseDecision("answer_no_match", ANSWER_ONLY_METRICS)

    if classification == "DECLINE":
        if matched and expected_classification == "DECLINE":
            return CaseDecision("decline_expects_decline", [])
        if matched and expected_classification == "ANSWER":
            return CaseDecision("decline_expects_answer", [])
        return CaseDecision("decline_no_match", [])

    raise ValueError(f"Unknown classification: {classification!r}")


def _passes(scores: Dict[str, Optional[float]], thresholds: Dict[str, float], metric: str) -> bool:
    value = scores.get(metric)
    if value is None:
        raise ValueError(f"Metric {metric!r} was required for this outcome but has no score")
    return value >= thresholds[metric]


def compute_outcomes(
    case: str,
    scores: Dict[str, Optional[float]],
    thresholds: Dict[str, float],
) -> Dict[str, str]:
    """Returns {"accurate": ..., "retrieval": ..., "relevant": ...} per spec 4.3."""

    if case == "clarify_matches_clarify":
        return {"accurate": "pass", "retrieval": "not_scored", "relevant": "not_scored"}

    if case == "clarify_other":
        return {"accurate": "skipped", "retrieval": "skipped", "relevant": "skipped"}

    if case == "answer_expects_clarify":
        relevant = "pass" if _passes(scores, thresholds, "response_relevancy") else "fail"
        return {"accurate": "unverified", "retrieval": "not_scored", "relevant": relevant}

    if case == "answer_matched_answer":
        accurate = (
            "pass"
            if _passes(scores, thresholds, "faithfulness") and _passes(scores, thresholds, "factual_correctness")
            else "fail"
        )
        retrieval = (
            "pass"
            if _passes(scores, thresholds, "context_recall") and _passes(scores, thresholds, "context_precision")
            else "fail"
        )
        relevant = "pass" if _passes(scores, thresholds, "response_relevancy") else "fail"
        return {"accurate": accurate, "retrieval": retrieval, "relevant": relevant}

    if case == "answer_no_match":
        relevant = "pass" if _passes(scores, thresholds, "response_relevancy") else "fail"
        return {"accurate": "unverified", "retrieval": "not_scored", "relevant": relevant}

    if case == "answer_expects_decline":
        # Faithfulness and Response Relevancy both run (spec 4.3), but only
        # `accurate` is derived from them; `relevant` stays not_scored per the
        # table even though the relevancy score is computed and returned.
        return {"accurate": "fail", "retrieval": "not_scored", "relevant": "not_scored"}

    if case == "decline_expects_decline":
        return {"accurate": "pass", "retrieval": "not_scored", "relevant": "not_scored"}

    if case == "decline_expects_answer":
        return {"accurate": "fail", "retrieval": "not_scored", "relevant": "not_scored"}

    if case == "decline_no_match":
        return {"accurate": "unverified", "retrieval": "not_scored", "relevant": "not_scored"}

    raise ValueError(f"Unknown case: {case!r}")


def error_outcomes() -> Dict[str, str]:
    return {"accurate": "error", "retrieval": "error", "relevant": "error"}
