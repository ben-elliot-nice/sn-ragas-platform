import pytest

from app.classification import ClassificationResult, classify_response
from tests.conftest import FakeChatModel


@pytest.mark.asyncio
async def test_classify_answer():
    model = FakeChatModel(
        structured_outputs={"ClassificationResult": ClassificationResult(label="answer", reason="It answered.")}
    )
    result = await classify_response("Does Plus cover diving?", "No, it does not.", model)
    assert result.label == "ANSWER"
    assert result.reason == "It answered."


@pytest.mark.asyncio
async def test_classify_clarify():
    model = FakeChatModel(
        structured_outputs={"ClassificationResult": ClassificationResult(label="CLARIFY", reason="Asked a question back.")}
    )
    result = await classify_response("What's my coverage?", "Which policy are you asking about?", model)
    assert result.label == "CLARIFY"


@pytest.mark.asyncio
async def test_classify_invalid_label_raises():
    model = FakeChatModel(
        structured_outputs={"ClassificationResult": ClassificationResult(label="MAYBE", reason="Unclear.")}
    )
    with pytest.raises(ValueError):
        await classify_response("q", "r", model)
