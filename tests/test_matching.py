import pytest

from app.matching import MatchJudgeOutput, match_reference
from tests.conftest import FakeChatModel, make_embed_query


@pytest.mark.asyncio
async def test_match_within_confidence_floor(sample_golden_set):
    model = FakeChatModel(
        structured_outputs={"MatchJudgeOutput": MatchJudgeOutput(reference_id="FAQ-001", confidence=0.9)}
    )
    embed_query = make_embed_query(default=(1.0, 0.0, 0.0))  # closest to FAQ-001

    result = await match_reference(
        standalone_query="Does Travel Plus cover scuba diving?",
        user_message="what about scuba on that plan?",
        recent_turns=[],
        golden_set=sample_golden_set,
        chat_model=model,
        embed_query=embed_query,
        confidence_floor=0.7,
    )

    assert result.reference_id == "FAQ-001"
    assert result.expected_classification == "ANSWER"
    assert set(result.candidates) == {"FAQ-001", "FAQ-002", "FAQ-003"}


@pytest.mark.asyncio
async def test_match_below_confidence_floor_is_none(sample_golden_set):
    model = FakeChatModel(
        structured_outputs={"MatchJudgeOutput": MatchJudgeOutput(reference_id="FAQ-001", confidence=0.5)}
    )
    embed_query = make_embed_query(default=(1.0, 0.0, 0.0))

    result = await match_reference(
        standalone_query="Does Travel Plus cover scuba diving?",
        user_message="...",
        recent_turns=[],
        golden_set=sample_golden_set,
        chat_model=model,
        embed_query=embed_query,
        confidence_floor=0.7,
    )

    assert result.reference_id is None
    assert result.expected_classification is None
    assert result.confidence == 0.5


@pytest.mark.asyncio
async def test_judge_picks_none(sample_golden_set):
    model = FakeChatModel(
        structured_outputs={"MatchJudgeOutput": MatchJudgeOutput(reference_id="none", confidence=0.95)}
    )
    embed_query = make_embed_query(default=(1.0, 0.0, 0.0))

    result = await match_reference(
        standalone_query="Does Travel Plus cover scuba diving?",
        user_message="...",
        recent_turns=[],
        golden_set=sample_golden_set,
        chat_model=model,
        embed_query=embed_query,
        confidence_floor=0.7,
    )

    assert result.reference_id is None


@pytest.mark.asyncio
async def test_empty_standalone_query_falls_back_to_rewrite(sample_golden_set):
    model = FakeChatModel(
        structured_outputs={"MatchJudgeOutput": MatchJudgeOutput(reference_id="FAQ-001", confidence=0.9)},
        plain_outputs=["Does Travel Plus cover scuba diving?"],
    )
    embed_query = make_embed_query(default=(1.0, 0.0, 0.0))

    result = await match_reference(
        standalone_query="",
        user_message="what about scuba?",
        recent_turns=[],
        golden_set=sample_golden_set,
        chat_model=model,
        embed_query=embed_query,
        confidence_floor=0.7,
    )

    assert len(model.calls) == 1  # the rewrite call happened
    assert result.reference_id == "FAQ-001"
