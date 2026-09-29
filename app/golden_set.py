"""Loads the golden set and its precomputed question embeddings (spec 6.1, 7.1)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class GoldenEntry:
    id: str
    category: str
    test_type: str
    canonical_question: str
    question_variants: List[str]
    reference_answer: str
    source_article_ids: List[str]
    source_chunk_ids: List[str]
    expected_classification: str
    notes: str = ""
    # One embedding per (canonical_question + each variant), same order as `questions`.
    questions: List[str] = field(default_factory=list)
    question_vectors: List[List[float]] = field(default_factory=list)


class GoldenSet:
    def __init__(self, version: str, kb_version: str, entries: List[GoldenEntry]):
        self.version = version
        self.kb_version = kb_version
        self.entries = entries
        self._by_id: Dict[str, GoldenEntry] = {e.id: e for e in entries}

    def get(self, reference_id: str) -> Optional[GoldenEntry]:
        return self._by_id.get(reference_id)

    @classmethod
    def load(cls, golden_set_path: Path, embeddings_path: Optional[Path] = None) -> "GoldenSet":
        raw = json.loads(Path(golden_set_path).read_text(encoding="utf-8"))
        entries = []
        for e in raw["entries"]:
            entries.append(
                GoldenEntry(
                    id=e["id"],
                    category=e["category"],
                    test_type=e["test_type"],
                    canonical_question=e["canonical_question"],
                    question_variants=e.get("question_variants", []),
                    reference_answer=e["reference_answer"],
                    source_article_ids=e.get("source_article_ids", []),
                    source_chunk_ids=e.get("source_chunk_ids", []),
                    expected_classification=e["expected_classification"],
                    notes=e.get("notes", ""),
                    questions=[e["canonical_question"], *e.get("question_variants", [])],
                )
            )
        golden_set = cls(version=raw["version"], kb_version=raw["kb_version"], entries=entries)

        if embeddings_path and Path(embeddings_path).exists():
            golden_set._load_cached_embeddings(Path(embeddings_path))
        else:
            logger.warning(
                "No precomputed golden set embeddings found at %s. Run "
                "scripts/precompute_golden_set_embeddings.py at build/deploy time; "
                "otherwise cold starts pay the full embedding cost (spec 6.1).",
                embeddings_path,
            )
        return golden_set

    def _load_cached_embeddings(self, path: Path) -> None:
        cache = json.loads(path.read_text(encoding="utf-8"))
        if cache.get("golden_set_version") != self.version:
            logger.warning(
                "Golden set embeddings cache is for version %s but loaded golden set is %s; ignoring cache.",
                cache.get("golden_set_version"),
                self.version,
            )
            return
        vectors_by_id = cache.get("entries", {})
        for entry in self.entries:
            cached = vectors_by_id.get(entry.id)
            if cached and len(cached) == len(entry.questions):
                entry.question_vectors = cached

    def needs_embeddings(self) -> bool:
        return any(len(e.question_vectors) != len(e.questions) for e in self.entries)

    async def ensure_embeddings(self, embed_fn) -> None:
        """Fallback path: embed on the fly for any entry missing cached vectors."""
        for entry in self.entries:
            if len(entry.question_vectors) == len(entry.questions):
                continue
            entry.question_vectors = await embed_fn(entry.questions)
