import json

import httpx
import pytest
from pydantic import ValidationError

from app.cognigy_analytics import (
    CognigyAnalyticsClient,
    analytics_contact_id,
    custom_fields_for_error,
    custom_fields_from_result,
)
from app.schemas import (
    EvaluateRequest,
    EvaluateResponse,
    MatchOut,
    OutcomesOut,
    RetrievalCheckOut,
    ScoresOut,
)


def make_request(**overrides):
    base = dict(
        session_id="s1",
        input_id="i1",
        run_id="2026-10-05-r1",
        user_message="how long does a cancellation take?",
        response="Up to 7 business days.",
        writeback=True,
        contact_id="user@example.com",
        project_id="6ab9d449a3709e53b89767da",
    )
    base.update(overrides)
    return EvaluateRequest(**base)


def make_result(**overrides):
    base = dict(
        eval_id="e1",
        golden_set_version="gs-v1",
        classification="ANSWER",
        match=MatchOut(reference_id=None, confidence=0.95, expected_classification=None, candidates=["FAQ-013"]),
        scores=ScoresOut(faithfulness=0.8, response_relevancy=0.8002870011007142),
        outcomes=OutcomesOut(accurate="unverified", retrieval="not_scored", relevant="pass"),
        retrieval_check=RetrievalCheckOut(expected_chunk_ids=[], retrieved_expected=0),
        ragas_version="0.3.9",
        judge_model="gpt-4.1",
    )
    base.update(overrides)
    return EvaluateResponse(**base)


def test_custom_fields_match_cognigy_code_node_mapping():
    fields = custom_fields_from_result(make_result(), "2026-10-05-r1")
    assert fields == {
        "custom1": "ANSWER",
        "custom2": "none",
        "custom3": "0.95",
        "custom4": "0.8",
        "custom5": "na",
        "custom6": "0.8002870011007142",
        "custom7": "na",
        "custom8": "na",
        "custom9": "A:unverified|R:not_scored|V:pass",
        "custom10": "2026-10-05-r1|gs-v1",
    }


def test_error_fields():
    assert custom_fields_for_error("r1", "judge_timeout") == {
        "custom9": "A:error|R:error|V:error",
        "custom10": "r1|error-judge_timeout",
    }


def test_contact_id_is_md5_of_user_id_like_cognigy_analytics():
    # Value read back from Cognigy OData for userId "simulation-claude-test".
    assert analytics_contact_id("simulation-claude-test") == "92af4721b6dcdf7952bc1133cfe9a179"


def test_writeback_requires_contact_and_project_ids():
    with pytest.raises(ValidationError):
        make_request(contact_id=None)
    # Sync mode doesn't need them.
    make_request(writeback=False, contact_id=None, project_id=None)


def _client(handler):
    return CognigyAnalyticsClient(
        "https://api.example.cognigy.ai/new/",
        "cognigy-key",
        initial_delay=0,
        retry_delays=(0.01, 0.01),
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_patch_sends_both_contact_id_forms():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(204)

    outcome = await _client(handler).patch_record(make_request(), {"custom9": "A:pass|R:pass|V:pass"})

    assert outcome["status"] == 204
    assert outcome["error"] is None
    assert outcome["attempts"] == 2
    assert [json.loads(r.content)["contactId"] for r in seen] == [
        "user@example.com",
        analytics_contact_id("user@example.com"),
    ]
    req = seen[0]
    assert req.method == "PATCH"
    assert str(req.url) == "https://api.example.cognigy.ai/new/v2.0/analytics"
    assert req.headers["X-API-Key"] == "cognigy-key"
    assert json.loads(req.content) == {
        "contactId": "user@example.com",
        "projectId": "6ab9d449a3709e53b89767da",
        "sessionId": "s1",
        "inputId": "i1",
        "properties": {"custom9": "A:pass|R:pass|V:pass"},
    }


@pytest.mark.asyncio
async def test_patch_succeeds_if_only_hashed_form_is_accepted():
    hashed = analytics_contact_id("user@example.com")

    def handler(req):
        if json.loads(req.content)["contactId"] == hashed:
            return httpx.Response(204)
        return httpx.Response(401, text="Invalid contact ID")

    outcome = await _client(handler).patch_record(make_request(), {})
    assert outcome["status"] == 204
    assert outcome["error"] is None
    assert outcome["by_contact_id"]["user@example.com"]["status"] == 401


@pytest.mark.asyncio
async def test_patch_retries_until_record_exists():
    statuses = [404, 404, 204]

    def handler(req):
        if json.loads(req.content)["contactId"] != "user@example.com":
            return httpx.Response(204)
        return httpx.Response(statuses.pop(0))

    outcome = await _client(handler).patch_record(make_request(), {})
    assert outcome["by_contact_id"]["user@example.com"] == {"status": 204, "attempts": 3, "error": None}


@pytest.mark.asyncio
async def test_patch_does_not_retry_auth_failure():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(401, text="bad key")

    outcome = await _client(handler).patch_record(make_request(), {})
    assert len(calls) == 2  # one per contactId form, no retries
    assert outcome["status"] == 401
    assert outcome["error"] == "bad key"


@pytest.mark.asyncio
async def test_patch_gives_up_after_retries_on_network_error():
    def handler(req):
        raise httpx.ConnectError("boom")

    outcome = await _client(handler).patch_record(make_request(), {})
    assert outcome["status"] is None
    assert outcome["attempts"] == 6  # 3 per contactId form
    assert "ConnectError" in outcome["error"]


@pytest.mark.asyncio
async def test_first_patch_waits_initial_delay():
    import time

    sent_at = []

    def handler(req):
        sent_at.append(time.monotonic())
        return httpx.Response(204)

    client = CognigyAnalyticsClient(
        "https://api.example.cognigy.ai/new",
        "k",
        initial_delay=0.2,
        transport=httpx.MockTransport(handler),
    )
    start = time.monotonic()
    await client.patch_record(make_request(), {})
    assert sent_at[0] - start >= 0.2
