"""Builds and runs the five Ragas metrics selected per spec 4.3 / 6.6.

Ragas 0.3.9 class names, confirmed against the pinned version (spec 6.6):
  Faithfulness              -> ragas.metrics.Faithfulness
  Factual Correctness (F1)  -> ragas.metrics.FactualCorrectness(mode="f1")
  Response Relevancy        -> ragas.metrics.ResponseRelevancy (needs embeddings)
  LLM-based Context Recall  -> ragas.metrics.LLMContextRecall
  Context Precision (ref.)  -> ragas.metrics.LLMContextPrecisionWithReference
"""
from __future__ import annotations

import asyncio
import re
from typing import Dict, List, Optional

from ragas import __version__ as RAGAS_VERSION
from ragas.dataset_schema import SingleTurnSample
from ragas.metrics import (
    FactualCorrectness,
    Faithfulness,
    LLMContextPrecisionWithReference,
    LLMContextRecall,
    ResponseRelevancy,
)

_CHUNK_PREFIX_RE = re.compile(r"^\s*\[[^\]]+\]\s*")


def strip_chunk_id_prefix(text: str) -> str:
    """Strips a leading "[chunk-id]" fallback prefix before passing text to Ragas (spec 7.4)."""
    return _CHUNK_PREFIX_RE.sub("", text, count=1)


def build_metrics(ragas_llm, ragas_embeddings) -> Dict[str, object]:
    return {
        "faithfulness": Faithfulness(llm=ragas_llm),
        "factual_correctness": FactualCorrectness(llm=ragas_llm, mode="f1"),
        "response_relevancy": ResponseRelevancy(llm=ragas_llm, embeddings=ragas_embeddings),
        "context_recall": LLMContextRecall(llm=ragas_llm),
        "context_precision": LLMContextPrecisionWithReference(llm=ragas_llm),
    }


def build_sample(
    *,
    user_input: str,
    response: str,
    retrieved_context_texts: List[str],
    reference: Optional[str],
) -> SingleTurnSample:
    return SingleTurnSample(
        user_input=user_input,
        response=response,
        retrieved_contexts=[strip_chunk_id_prefix(t) for t in retrieved_context_texts],
        reference=reference,
    )


async def run_selected_metrics(
    metric_names: List[str],
    sample: SingleTurnSample,
    metrics_by_name: Dict[str, object],
    timeout: Optional[float] = None,
) -> Dict[str, float]:
    if not metric_names:
        return {}

    async def _score_one(name: str) -> float:
        metric = metrics_by_name[name]
        return await metric.single_turn_ascore(sample, timeout=timeout)

    results = await asyncio.gather(*(_score_one(name) for name in metric_names))
    return dict(zip(metric_names, results))
