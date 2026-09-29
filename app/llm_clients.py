"""OpenAI clients: judge LLM and embedding model, plus their Ragas wrappers.

Judge LLM (gpt-4.1, temperature 0) must differ from whatever model the AI
Agent itself uses (spec 6.1). Embedding model is text-embedding-3-small.
Both go through the plain OpenAI API (not Azure OpenAI) since hosting moved
to Railway.
"""
from __future__ import annotations

from typing import List

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper

from .config import settings


def build_judge_chat_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.judge_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )


def build_embedding_model() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.openai_api_key,
    )


class EmbeddingClient:
    """Thin async facade so callers don't depend on the langchain embeddings API shape."""

    def __init__(self, embeddings: OpenAIEmbeddings):
        self._embeddings = embeddings

    async def embed_query(self, text: str) -> List[float]:
        return await self._embeddings.aembed_query(text)

    async def embed_many(self, texts: List[str]) -> List[List[float]]:
        return await self._embeddings.aembed_documents(texts)


class Clients:
    """Lazily built, process-wide clients. Built once per worker process."""

    def __init__(self) -> None:
        self._chat_model = None
        self._embedding_model = None
        self._embedding_client = None

    @property
    def judge_chat_model(self) -> ChatOpenAI:
        if self._chat_model is None:
            self._chat_model = build_judge_chat_model()
        return self._chat_model

    @property
    def embedding_model(self) -> OpenAIEmbeddings:
        if self._embedding_model is None:
            self._embedding_model = build_embedding_model()
        return self._embedding_model

    @property
    def embedding_client(self) -> EmbeddingClient:
        if self._embedding_client is None:
            self._embedding_client = EmbeddingClient(self.embedding_model)
        return self._embedding_client

    @property
    def ragas_llm(self) -> LangchainLLMWrapper:
        return LangchainLLMWrapper(self.judge_chat_model)

    @property
    def ragas_embeddings(self) -> LangchainEmbeddingsWrapper:
        return LangchainEmbeddingsWrapper(self.embedding_model)


clients = Clients()
