import json

import pytest

from app.classification import ClassificationResult
from app.evaluate import EvaluationDeps, evaluate
from app.matching import MatchJudgeOutput
from app.result_log import ResultLog
from app.schemas import EvaluateRequest, RetrievedContext
from tests.conftest import FakeChatModel, make_embed_query


class FakeMetric:
    def __init__(self, score: float):
        self.score = score

    async def single_turn_ascore(self, sample, timeout=None):
        return self.score


FAKE_METRICS = {
    "faithfulness": FakeMetric(0.95),
    "factual_correctness": FakeMetric(0.85),
    "response_relevancy": FakeMetric(0.9),
    "context_recall": FakeMetric(0.9),
    "context_precision": FakeMetric(0.9),
}


def make_request(**overrides):
    base = dict(
        session_id="s1",
        input_id="i1",
        run_id="2026-10-01-r1",
        user_message="what about scuba on that plan?",
        standalone_query="Does Travel Plus cover scuba diving?",
        recent_turns=[],
        response="Travel Plus does not cover scuba diving.",
        retrieved_contexts=[
            RetrievedContext(chunk_id="KB-TRV-003-01", source_id="KB-TRV-003", text="...", rank=1)
        ],
    )
    base.update(overrides)
    return EvaluateRequest(**base)


@pytest.mark.asyncio
async def test_full_answer_matched_pipeline(sample_golden_set, tmp_path):
    log_path = tmp_path / "eval_log.jsonl"
    chat_model = FakeChatModel(
        structured_outputs={
            "ClassificationResult": ClassificationResult(label="ANSWER", reason="It answered."),
            "MatchJudgeOutput": MatchJudgeOutput(reference_id="FAQ-001", confidence=0.9),
        }
    )
    deps = EvaluationDeps(
        chat_model=chat_model,
        embed_query=make_embed_query(default=(1.0, 0.0, 0.0)),
        golden_set=sample_golden_set,
        metrics_by_name=FAKE_METRICS,
        thresholds={
            "faithfulness": 0.80,
            "factual_correctness": 0.70,
            "response_relevancy": 0.75,
            "context_recall": 0.80,
            "context_precision": 0.70,
        },
        confidence_floor=0.7,
        result_log=ResultLog(f"local:{log_path}"),
        judge_model_name="gpt-4.1",
        golden_set_version="gs-test",
    )

    response = await evaluate(make_request(), deps)

    assert response.classification == "ANSWER"
    assert response.match.reference_id == "FAQ-001"
    assert response.scores.faithfulness == 0.95
    assert response.outcomes.accurate == "pass"
    assert response.outcomes.retrieval == "pass"
    assert response.outcomes.relevant == "pass"
    assert response.retrieval_check.expected_chunk_ids == ["KB-TRV-003-01"]
    assert response.retrieval_check.retrieved_expected == 1
    assert response.ragas_version
    assert response.judge_model == "gpt-4.1"

    logged = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(logged) == 1
    assert logged[0]["session_id"] == "s1"
    assert logged[0]["input_id"] == "i1"
    assert logged[0]["case"] == "answer_matched_answer"


@pytest.mark.asyncio
async def test_clarify_other_runs_no_metrics(sample_golden_set, tmp_path):
    log_path = tmp_path / "eval_log.jsonl"
    chat_model = FakeChatModel(
        structured_outputs={
            "ClassificationResult": ClassificationResult(label="CLARIFY", reason="Asked a follow-up question."),
            "MatchJudgeOutput": MatchJudgeOutput(reference_id="none", confidence=0.95),
        }
    )
    deps = EvaluationDeps(
        chat_model=chat_model,
        embed_query=make_embed_query(default=(1.0, 0.0, 0.0)),
        golden_set=sample_golden_set,
        metrics_by_name=FAKE_METRICS,
        thresholds={
            "faithfulness": 0.80,
            "factual_correctness": 0.70,
            "response_relevancy": 0.75,
            "context_recall": 0.80,
            "context_precision": 0.70,
        },
        confidence_floor=0.7,
        result_log=ResultLog(f"local:{log_path}"),
        judge_model_name="gpt-4.1",
        golden_set_version="gs-test",
    )

    response = await evaluate(
        make_request(response="Could you tell me which policy you mean?", retrieved_contexts=[]), deps
    )

    assert response.classification == "CLARIFY"
    assert response.match.reference_id is None
    assert response.scores.model_dump() == {
        "faithfulness": None,
        "factual_correctness": None,
        "response_relevancy": None,
        "context_recall": None,
        "context_precision": None,
    }
    assert response.outcomes.accurate == "skipped"
    assert response.outcomes.retrieval == "skipped"
    assert response.outcomes.relevant == "skipped"
    assert response.retrieval_check.expected_chunk_ids == []
