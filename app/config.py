"""Environment-driven configuration. See build spec section 6.8.

Hosting pivot: this runs on Railway (a plain Python HTTP process) using the
OpenAI API directly, not Azure Functions / Azure OpenAI as originally
"Decided" in spec 6.1. Judge model is still gpt-4.1 at temperature 0 and
must still differ from whatever model the AI Agent itself uses; embedding
model is still text-embedding-3-small. Only the hosting/provider layer
changed, not the metrics, outcome rules, or API contract.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

# Loads ragas-poc/service/.env for local dev. Railway sets real env vars via
# its dashboard, so this is a no-op in production (no .env file is deployed).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Ragas usage telemetry is on by default and POSTs to its tracking server
# synchronously on every prompt/embedding call, blocking the event loop
# (~6.5s blocked per eval, measured 6 Oct 2026). That stalled /health and new
# /evaluate requests while a background eval ran, and roughly doubled eval
# time. Off unless explicitly set otherwise.
os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")

DEFAULT_THRESHOLDS = {
    "faithfulness": 0.80,
    "factual_correctness": 0.70,
    "response_relevancy": 0.75,
    "context_recall": 0.80,
    "context_precision": 0.70,
}

_SERVICE_ROOT = Path(__file__).resolve().parent.parent


class Settings:
    def __init__(self) -> None:
        self.api_key = os.environ.get("API_KEY", "")

        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
        self.judge_model = os.environ.get("JUDGE_MODEL", "gpt-4.1")
        self.embedding_model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

        # Bundled inside the service folder (spec 6.1: "bundled in the deployment")
        # so the deployable unit is self-contained for Railway/zip handoff.
        self.golden_set_path = self._resolve_path(
            os.environ.get("GOLDEN_SET_PATH", str(_SERVICE_ROOT / "data" / "golden_set.json"))
        )
        self.golden_set_embeddings_path = self._resolve_path(
            os.environ.get(
                "GOLDEN_SET_EMBEDDINGS_PATH",
                str(_SERVICE_ROOT / "data" / "golden_set.embeddings.json"),
            )
        )

        self.match_confidence_floor = float(os.environ.get("MATCH_CONFIDENCE_FLOOR", "0.7"))
        self.log_destination = os.environ.get("LOG_DESTINATION", "local:./eval_log.jsonl")

        # Async mode write-back (PATCH /v2.0/analytics). Base URL is the
        # Cognigy REST API root up to (not including) /v2.0, e.g.
        # https://api-trial.cognigy.ai/new
        self.cognigy_api_base_url = os.environ.get("COGNIGY_API_BASE_URL", "")
        self.cognigy_api_key = os.environ.get("COGNIGY_API_KEY", "")

        raw_thresholds = os.environ.get("THRESHOLDS", "").strip()
        overrides = json.loads(raw_thresholds) if raw_thresholds else {}
        self.thresholds = {**DEFAULT_THRESHOLDS, **overrides}

    @staticmethod
    def _resolve_path(value: str) -> Path:
        p = Path(value)
        if not p.is_absolute():
            p = (_SERVICE_ROOT / p).resolve()
        return p


settings = Settings()

# The two Azure TBD items from build spec section 12 (Flex Consumption
# region availability, Global Standard deployability) no longer apply now
# that hosting moved to Railway with direct OpenAI API access. If this
# service ever needs to move back to Azure for data-residency reasons
# (spec 6.1's note on real client data), those items resurface then.
OPEN_TBD_ITEMS: list[str] = []
