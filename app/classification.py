"""Response classification (spec 6.4). Runs before any scoring.

A "response ends with ?" heuristic is explicitly rejected by the spec, since
answers often end with "Anything else I can help with?" — this must be a
judge call, not a string check.
"""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

CLASSIFY_SYSTEM_PROMPT = """You classify a virtual agent's response to a customer question.

Labels:
- ANSWER: the response provides information in response to the question.
- CLARIFY: the response asks the user for more information before answering.
- DECLINE: the response states it cannot help, or hands off to a human/other channel.

A response that answers the question and then adds a closing pleasantry
("Anything else I can help with?") is still ANSWER, not CLARIFY. Judge only
the substantive content of the response.

Respond with the label and a one-sentence reason."""


class ClassificationResult(BaseModel):
    label: str = Field(description="One of ANSWER, CLARIFY, DECLINE")
    reason: str


class ChatModel(Protocol):
    async def ainvoke(self, messages: list) -> object: ...


async def classify_response(standalone_query: str, response: str, chat_model) -> ClassificationResult:
    structured_model = chat_model.with_structured_output(ClassificationResult)
    result = await structured_model.ainvoke(
        [
            ("system", CLASSIFY_SYSTEM_PROMPT),
            (
                "user",
                f"Question: {standalone_query}\n\nResponse: {response}",
            ),
        ]
    )
    label = result.label.strip().upper()
    if label not in ("ANSWER", "CLARIFY", "DECLINE"):
        raise ValueError(f"Judge returned an invalid classification label: {label!r}")
    return ClassificationResult(label=label, reason=result.reason)
