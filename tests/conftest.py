import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.golden_set import GoldenEntry, GoldenSet


class FakeStructuredModel:
    def __init__(self, output):
        self._output = output

    async def ainvoke(self, messages):
        if isinstance(self._output, list):
            return self._output.pop(0)
        return self._output


class FakePlainResult:
    def __init__(self, content: str):
        self.content = content


class FakeChatModel:
    """Stands in for AzureChatOpenAI in tests. No network calls.

    - structured_outputs: {PydanticClassName: value_or_list_of_values}
    - plain_outputs: list of strings consumed in order by plain .ainvoke() calls
      (used for the standalone-query rewrite path).
    """

    def __init__(self, structured_outputs=None, plain_outputs=None):
        self.structured_outputs = structured_outputs or {}
        self.plain_outputs = list(plain_outputs or [])
        self.calls = []

    def with_structured_output(self, schema):
        return FakeStructuredModel(self.structured_outputs[schema.__name__])

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return FakePlainResult(self.plain_outputs.pop(0) if self.plain_outputs else "")


def make_embed_query(vector_by_text=None, default=(1.0, 0.0, 0.0)):
    vector_by_text = vector_by_text or {}

    async def embed_query(text: str):
        return list(vector_by_text.get(text, default))

    return embed_query


@pytest.fixture
def sample_golden_set() -> GoldenSet:
    entries = [
        GoldenEntry(
            id="FAQ-001",
            category="Travel",
            test_type="single_fact",
            canonical_question="Does Travel Plus cover scuba diving?",
            question_variants=["Is diving covered on Plus?"],
            reference_answer="No. Travel Plus does not cover scuba diving.",
            source_article_ids=["KB-TRV-003"],
            source_chunk_ids=["KB-TRV-003-01"],
            expected_classification="ANSWER",
            questions=["Does Travel Plus cover scuba diving?", "Is diving covered on Plus?"],
            question_vectors=[[1.0, 0.0, 0.0], [0.9, 0.1, 0.0]],
        ),
        GoldenEntry(
            id="FAQ-002",
            category="General",
            test_type="not_covered",
            canonical_question="Can you help me file a car insurance claim?",
            question_variants=[],
            reference_answer="",
            source_article_ids=[],
            source_chunk_ids=[],
            expected_classification="DECLINE",
            questions=["Can you help me file a car insurance claim?"],
            question_vectors=[[0.0, 1.0, 0.0]],
        ),
        GoldenEntry(
            id="FAQ-003",
            category="General",
            test_type="ambiguous",
            canonical_question="What's my coverage?",
            question_variants=[],
            reference_answer="",
            source_article_ids=[],
            source_chunk_ids=[],
            expected_classification="CLARIFY",
            questions=["What's my coverage?"],
            question_vectors=[[0.0, 0.0, 1.0]],
        ),
    ]
    return GoldenSet(version="gs-test", kb_version="kb-test", entries=entries)
