import json

from app.schemas import EvaluateRequest, EvaluateResponse, MatchOut, OutcomesOut, RetrievalCheckOut, ScoresOut


def test_request_matches_spec_example():
    payload = {
        "session_id": "sess-1",
        "input_id": "input-1",
        "run_id": "2026-10-01-r1",
        "user_message": "what about scuba on that plan?",
        "standalone_query": "Does Travel Plus cover scuba diving",
        "recent_turns": [
            {"role": "user", "text": "Is snorkelling covered on Travel Plus?"},
            {"role": "assistant", "text": "Yes, Travel Plus covers snorkelling."},
        ],
        "response": "Travel Plus does not cover scuba diving...",
        "retrieved_contexts": [
            {"chunk_id": "KB-TRV-003-01", "source_id": "KB-TRV-003", "text": "...", "rank": 1}
        ],
    }
    request = EvaluateRequest.model_validate(payload)
    assert request.session_id == "sess-1"
    assert request.retrieved_contexts[0].rank == 1


def test_response_round_trip_matches_spec_shape():
    response = EvaluateResponse(
        eval_id="11111111-1111-1111-1111-111111111111",
        golden_set_version="gs-v1",
        classification="ANSWER",
        match=MatchOut(
            reference_id="FAQ-022",
            confidence=0.91,
            expected_classification="ANSWER",
            candidates=["FAQ-022", "FAQ-023", "FAQ-056"],
        ),
        scores=ScoresOut(
            faithfulness=1.0,
            factual_correctness=0.67,
            response_relevancy=0.88,
            context_recall=0.67,
            context_precision=0.83,
        ),
        outcomes=OutcomesOut(accurate="fail", retrieval="fail", relevant="pass"),
        retrieval_check=RetrievalCheckOut(
            expected_chunk_ids=["KB-TRV-003-01", "KB-TRV-002-01"], retrieved_expected=1
        ),
        ragas_version="0.3.9",
        judge_model="gpt-4.1",
    )
    body = json.loads(response.model_dump_json())
    assert set(body.keys()) == {
        "eval_id",
        "golden_set_version",
        "classification",
        "match",
        "scores",
        "outcomes",
        "retrieval_check",
        "ragas_version",
        "judge_model",
    }
    assert body["match"]["reference_id"] == "FAQ-022"


def test_scores_default_to_null():
    scores = ScoresOut()
    body = json.loads(scores.model_dump_json())
    assert body == {
        "faithfulness": None,
        "factual_correctness": None,
        "response_relevancy": None,
        "context_recall": None,
        "context_precision": None,
    }
