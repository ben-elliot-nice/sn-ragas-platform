"""Writes eval results back onto the Cognigy analytics record (spec 5.7) via
PATCH /v2.0/analytics, keyed by contactId + projectId + sessionId + inputId.

Used by the async /evaluate mode: Cognigy's HTTP service gives up after a
hard 15s, and a full eval regularly takes 10-22s, so the service answers 202
immediately and writes custom1-custom10 itself once scoring finishes.

The PATCH merges: only the properties sent are changed (confirmed 5 Oct 2026),
so sending custom1-custom10 leaves intent, flowName etc. untouched.

contactId on the analytics record depends on the channel (confirmed 7 Oct
2026 via OData): REST stores md5(userId) ("simulation-claude-test" ->
"92af4721b6dcdf7952bc1133cfe9a179"), the Interaction Panel (adminconsole)
stores the plain userId ("shannon.nguyen@nice.com"). The flow sends the plain
userId as contact_id, so the PATCH is sent with both forms. Only the one that
matches the record changes anything.

The first PATCH waits COGNIGY_WRITEBACK_DELAY_SECONDS (default 30). Writes
sent ~8s after the turn (straight after scoring) were accepted but never
showed up on the record, while the same write sent 24s+ after the turn
landed every time (tested 7 Oct 2026). Cognigy evidently hasn't stored the
turn's analytics record yet that soon after the turn, and doesn't report an
error, so the 404/400 retries below never fire for it.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Dict, Optional, Sequence

import httpx

from .schemas import EvaluateRequest, EvaluateResponse

logger = logging.getLogger(__name__)

NA = "na"
INITIAL_DELAY_SECONDS: float = 30
RETRY_DELAYS_SECONDS: Sequence[float] = (2, 5, 10, 20)
# 400 is retried as well as 404: a PATCH for a record that doesn't exist yet
# may come back as either.
RETRYABLE_STATUSES = {400, 404, 408, 429, 500, 502, 503, 504}


def _fmt(value) -> str:
    return str(value) if value is not None else NA


def analytics_contact_id(user_id: str) -> str:
    return hashlib.md5(user_id.encode("utf-8")).hexdigest()


def custom_fields_from_result(result: EvaluateResponse, run_id: str) -> Dict[str, str]:
    """Same mapping the Cognigy parse Code Node used (spec 5.7)."""
    o = result.outcomes
    return {
        "custom1": result.classification or NA,
        "custom2": result.match.reference_id or "none",
        "custom3": _fmt(result.match.confidence),
        "custom4": _fmt(result.scores.faithfulness),
        "custom5": _fmt(result.scores.factual_correctness),
        "custom6": _fmt(result.scores.response_relevancy),
        "custom7": _fmt(result.scores.context_recall),
        "custom8": _fmt(result.scores.context_precision),
        "custom9": f"A:{o.accurate}|R:{o.retrieval}|V:{o.relevant}",
        "custom10": f"{run_id or 'unset-run-id'}|{result.golden_set_version or 'unset-gs'}",
    }


def custom_fields_for_error(run_id: str, error_code: str) -> Dict[str, str]:
    return {
        "custom9": "A:error|R:error|V:error",
        "custom10": f"{run_id or 'unset-run-id'}|error-{error_code}",
    }


class CognigyAnalyticsClient:
    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        initial_delay: float = INITIAL_DELAY_SECONDS,
        retry_delays: Sequence[float] = RETRY_DELAYS_SECONDS,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.url = api_base_url.rstrip("/") + "/v2.0/analytics"
        self.api_key = api_key
        self.initial_delay = initial_delay
        self.retry_delays = retry_delays
        self._transport = transport

    async def patch_record(self, request: EvaluateRequest, properties: Dict[str, str]) -> Dict:
        """PATCHes the record with each contactId form (plain, then MD5),
        retrying each on transient/not-yet-written failures.
        Returns {"status", "attempts", "error", "by_contact_id"}; status/error
        are from the first form that succeeded, else the last one tried."""
        headers = {"Content-Type": "application/json", "X-API-Key": self.api_key}
        contact_ids = list(dict.fromkeys([request.contact_id, analytics_contact_id(request.contact_id)]))

        if self.initial_delay:
            await asyncio.sleep(self.initial_delay)

        outcomes = []
        async with httpx.AsyncClient(timeout=15, transport=self._transport) as client:
            for contact_id in contact_ids:
                body = {
                    "contactId": contact_id,
                    "projectId": request.project_id,
                    "sessionId": request.session_id,
                    "inputId": request.input_id,
                    "properties": properties,
                }
                outcomes.append((contact_id, await self._patch_with_retries(client, body, headers)))

        succeeded = [o for _, o in outcomes if o["error"] is None]
        chosen = succeeded[0] if succeeded else outcomes[-1][1]
        result = {
            "status": chosen["status"],
            "attempts": sum(o["attempts"] for _, o in outcomes),
            "error": chosen["error"],
            "by_contact_id": {cid: o for cid, o in outcomes},
        }
        if not succeeded:
            logger.warning(
                "Cognigy analytics PATCH failed for session=%s input=%s: %s",
                request.session_id, request.input_id, result["by_contact_id"],
            )
        return result

    async def _patch_with_retries(self, client: httpx.AsyncClient, body: Dict, headers: Dict) -> Dict:
        status: Optional[int] = None
        error: Optional[str] = None
        attempts = 0
        for delay in (0, *self.retry_delays):
            if delay:
                await asyncio.sleep(delay)
            attempts += 1
            try:
                resp = await client.patch(self.url, json=body, headers=headers)
                status, error = resp.status_code, None
                if resp.is_success:
                    return {"status": status, "attempts": attempts, "error": None}
                error = resp.text[:500]
                if status not in RETRYABLE_STATUSES:
                    break
            except httpx.HTTPError as e:
                status, error = None, f"{type(e).__name__}: {e}"
        return {"status": status, "attempts": attempts, "error": error}
