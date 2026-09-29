import pytest

from app.outcomes import ALL_METRICS, ANSWER_ONLY_METRICS, compute_outcomes, decide_case, error_outcomes

THRESHOLDS = {
    "faithfulness": 0.80,
    "factual_correctness": 0.70,
    "response_relevancy": 0.75,
    "context_recall": 0.80,
    "context_precision": 0.70,
}

PASSING_ALL = {
    "faithfulness": 1.0,
    "factual_correctness": 1.0,
    "response_relevancy": 1.0,
    "context_recall": 1.0,
    "context_precision": 1.0,
}


def test_clarify_matches_clarify():
    decision = decide_case("CLARIFY", matched=True, expected_classification="CLARIFY")
    assert decision.case == "clarify_matches_clarify"
    assert decision.metrics_to_run == []
    outcomes = compute_outcomes(decision.case, {}, THRESHOLDS)
    assert outcomes == {"accurate": "pass", "retrieval": "not_scored", "relevant": "not_scored"}


@pytest.mark.parametrize(
    "matched,expected",
    [(False, None), (True, "ANSWER"), (True, "DECLINE")],
)
def test_clarify_other(matched, expected):
    decision = decide_case("CLARIFY", matched=matched, expected_classification=expected)
    assert decision.case == "clarify_other"
    assert decision.metrics_to_run == []
    outcomes = compute_outcomes(decision.case, {}, THRESHOLDS)
    assert outcomes == {"accurate": "skipped", "retrieval": "skipped", "relevant": "skipped"}


def test_answer_expects_clarify_relevant_pass():
    decision = decide_case("ANSWER", matched=True, expected_classification="CLARIFY")
    assert decision.case == "answer_expects_clarify"
    assert decision.metrics_to_run == ANSWER_ONLY_METRICS
    outcomes = compute_outcomes(decision.case, {"faithfulness": 0.9, "response_relevancy": 0.9}, THRESHOLDS)
    assert outcomes == {"accurate": "unverified", "retrieval": "not_scored", "relevant": "pass"}


def test_answer_expects_clarify_relevant_fail():
    decision = decide_case("ANSWER", matched=True, expected_classification="CLARIFY")
    outcomes = compute_outcomes(decision.case, {"faithfulness": 0.9, "response_relevancy": 0.1}, THRESHOLDS)
    assert outcomes["relevant"] == "fail"


def test_answer_matched_answer_all_pass():
    decision = decide_case("ANSWER", matched=True, expected_classification="ANSWER")
    assert decision.case == "answer_matched_answer"
    assert decision.metrics_to_run == ALL_METRICS
    outcomes = compute_outcomes(decision.case, PASSING_ALL, THRESHOLDS)
    assert outcomes == {"accurate": "pass", "retrieval": "pass", "relevant": "pass"}


def test_answer_matched_answer_partial_failures():
    decision = decide_case("ANSWER", matched=True, expected_classification="ANSWER")
    scores = {**PASSING_ALL, "factual_correctness": 0.1, "context_precision": 0.1}
    outcomes = compute_outcomes(decision.case, scores, THRESHOLDS)
    # faithfulness passes but factual_correctness fails -> accurate fails
    assert outcomes["accurate"] == "fail"
    # context_recall passes but context_precision fails -> retrieval fails
    assert outcomes["retrieval"] == "fail"
    assert outcomes["relevant"] == "pass"


def test_answer_no_match():
    decision = decide_case("ANSWER", matched=False, expected_classification=None)
    assert decision.case == "answer_no_match"
    assert decision.metrics_to_run == ANSWER_ONLY_METRICS
    outcomes = compute_outcomes(decision.case, {"faithfulness": 0.9, "response_relevancy": 0.9}, THRESHOLDS)
    assert outcomes == {"accurate": "unverified", "retrieval": "not_scored", "relevant": "pass"}


def test_answer_expects_decline():
    decision = decide_case("ANSWER", matched=True, expected_classification="DECLINE")
    assert decision.case == "answer_expects_decline"
    assert decision.metrics_to_run == ANSWER_ONLY_METRICS
    # relevant stays not_scored even though response_relevancy was computed
    outcomes = compute_outcomes(decision.case, {"faithfulness": 0.9, "response_relevancy": 0.95}, THRESHOLDS)
    assert outcomes == {"accurate": "fail", "retrieval": "not_scored", "relevant": "not_scored"}


def test_decline_expects_decline():
    decision = decide_case("DECLINE", matched=True, expected_classification="DECLINE")
    assert decision.metrics_to_run == []
    outcomes = compute_outcomes(decision.case, {}, THRESHOLDS)
    assert outcomes == {"accurate": "pass", "retrieval": "not_scored", "relevant": "not_scored"}


def test_decline_expects_answer():
    decision = decide_case("DECLINE", matched=True, expected_classification="ANSWER")
    outcomes = compute_outcomes(decision.case, {}, THRESHOLDS)
    assert outcomes == {"accurate": "fail", "retrieval": "not_scored", "relevant": "not_scored"}


def test_decline_no_match():
    decision = decide_case("DECLINE", matched=False, expected_classification=None)
    outcomes = compute_outcomes(decision.case, {}, THRESHOLDS)
    assert outcomes == {"accurate": "unverified", "retrieval": "not_scored", "relevant": "not_scored"}


def test_error_outcomes():
    assert error_outcomes() == {"accurate": "error", "retrieval": "error", "relevant": "error"}


def test_missing_required_score_raises():
    decision = decide_case("ANSWER", matched=True, expected_classification="ANSWER")
    with pytest.raises(ValueError):
        compute_outcomes(decision.case, {"faithfulness": 0.9}, THRESHOLDS)


def test_unknown_classification_raises():
    with pytest.raises(ValueError):
        decide_case("MAYBE", matched=False, expected_classification=None)
