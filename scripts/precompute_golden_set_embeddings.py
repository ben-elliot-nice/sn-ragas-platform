"""Precomputes golden set question embeddings at build/deploy time (spec 6.1):

    "Precompute golden set embeddings at build time so startup does not embed
    60+ entries on every cold start."

Run once whenever golden_set.json changes, before deploying:

    python scripts/precompute_golden_set_embeddings.py

Requires EMBEDDING_* env vars (see local.settings.json.example) since it
calls the real Azure OpenAI embedding deployment. Writes
GOLDEN_SET_EMBEDDINGS_PATH (default: ../golden_set.embeddings.json).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.golden_set import GoldenSet  # noqa: E402
from app.llm_clients import clients  # noqa: E402


async def main() -> None:
    golden_set = GoldenSet.load(settings.golden_set_path, embeddings_path=None)
    await golden_set.ensure_embeddings(clients.embedding_client.embed_many)

    out = {
        "golden_set_version": golden_set.version,
        "entries": {e.id: e.question_vectors for e in golden_set.entries},
    }
    settings.golden_set_embeddings_path.write_text(json.dumps(out), encoding="utf-8")
    print(f"Wrote embeddings for {len(golden_set.entries)} entries to {settings.golden_set_embeddings_path}")


if __name__ == "__main__":
    asyncio.run(main())
