"""FastAPI entrypoint for POST /evaluate (spec 6.2), deployed to Railway.

Two modes:
  - sync (default): scores, then returns 200 with the full result.
  - async (`writeback: true`): returns 202 immediately, scores in the
    background, then PATCHes custom1-custom10 onto the Cognigy analytics
    record. Needed because Cognigy's HTTP service has a hard 15s cap and an
    eval regularly takes 10-22s.

Auth is a custom X-API-Key header check against API_KEY. Golden set and
Ragas metric objects are built once at process startup (Railway runs a
persistent worker, so there's no cold-start-per-request concern the way
there is on serverless).
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import BackgroundTasks, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.cognigy_analytics import CognigyAnalyticsClient, custom_fields_for_error, custom_fields_from_result
from app.config import OPEN_TBD_ITEMS, settings
from app.evaluate import EvaluationDeps, error_result_log_record, evaluate
from app.golden_set import GoldenSet
from app.llm_clients import clients
from app.metrics import build_metrics
from app.result_log import ResultLog
from app.schemas import AcceptedResponse, EvaluateRequest, EvaluateResponse

logger = logging.getLogger(__name__)

app = FastAPI(title="FAQ RAG Ragas Evaluation Service")

_golden_set: GoldenSet | None = None
_metrics_by_name = None
_result_log = ResultLog(settings.log_destination)


@app.on_event("startup")
async def startup() -> None:
    global _golden_set, _metrics_by_name
    if OPEN_TBD_ITEMS:
        logger.info("Startup TBD items: %s", OPEN_TBD_ITEMS)

    _golden_set = GoldenSet.load(settings.golden_set_path, settings.golden_set_embeddings_path)
    if _golden_set.needs_embeddings():
        logger.warning("Embedding golden set entries on the fly at startup (no precomputed cache found).")
        await _golden_set.ensure_embeddings(clients.embedding_client.embed_many)

    _metrics_by_name = build_metrics(clients.new_ragas_llm, clients.ragas_embeddings)


def _error_body(status: int, error_code: str, message: str, eval_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": error_code, "message": message, "eval_id": eval_id}
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _evaluate_and_write_back(request_model: EvaluateRequest, deps: EvaluationDeps, eval_id: str) -> None:
    """Background half of async mode. Never raises: every path ends in a
    PATCH (result or error fields) plus a writeback line in the result log."""
    try:
        result = await evaluate(request_model, deps, eval_id=eval_id)
        properties = custom_fields_from_result(result, request_model.run_id)
    except asyncio.TimeoutError:
        _result_log.write(
            error_result_log_record(eval_id, request_model.model_dump(), "judge_timeout", "Judge LLM call timed out.")
        )
        properties = custom_fields_for_error(request_model.run_id, "judge_timeout")
    except Exception as e:  # noqa: BLE001 - background task has no caller to raise to
        logger.exception("Unhandled error evaluating request (async)")
        _result_log.write(error_result_log_record(eval_id, request_model.model_dump(), "internal_error", str(e)))
        properties = custom_fields_for_error(request_model.run_id, "internal_error")

    client = CognigyAnalyticsClient(
        settings.cognigy_api_base_url,
        settings.cognigy_api_key,
        initial_delay=settings.cognigy_writeback_delay_seconds,
    )
    outcome = await client.patch_record(request_model, properties)
    _result_log.write(
        {
            "type": "writeback",
            "eval_id": eval_id,
            "session_id": request_model.session_id,
            "input_id": request_model.input_id,
            "properties": properties,
            **outcome,
        }
    )


@app.post("/evaluate")
async def evaluate_endpoint(
    request: Request, background_tasks: BackgroundTasks, x_api_key: str = Header(default="")
):
    eval_id = str(uuid.uuid4())

    if not settings.api_key or x_api_key != settings.api_key:
        return _error_body(401, "auth", "Missing or invalid X-API-Key.", eval_id)

    try:
        payload = await request.json()
    except Exception:
        return _error_body(400, "invalid_payload", "Request body is not valid JSON.", eval_id)

    try:
        request_model = EvaluateRequest.model_validate(payload)
    except ValidationError as e:
        return _error_body(400, "invalid_payload", str(e), eval_id)

    deps = EvaluationDeps(
        chat_model=clients.judge_chat_model,
        embed_query=clients.embedding_client.embed_query,
        golden_set=_golden_set,
        metrics_by_name=_metrics_by_name,
        thresholds=settings.thresholds,
        confidence_floor=settings.match_confidence_floor,
        result_log=_result_log,
        judge_model_name=settings.judge_model,
        golden_set_version=_golden_set.version,
    )

    if request_model.writeback:
        if not (settings.cognigy_api_base_url and settings.cognigy_api_key):
            return _error_body(
                500, "config", "writeback requested but COGNIGY_API_BASE_URL / COGNIGY_API_KEY are not set.", eval_id
            )
        background_tasks.add_task(_evaluate_and_write_back, request_model, deps, eval_id)
        return JSONResponse(status_code=202, content=AcceptedResponse(eval_id=eval_id).model_dump())

    try:
        response_model: EvaluateResponse = await evaluate(request_model, deps)
    except asyncio.TimeoutError:
        _result_log.write(
            error_result_log_record(eval_id, request_model.model_dump(), "judge_timeout", "Judge LLM call timed out.")
        )
        return _error_body(504, "judge_timeout", "Judge LLM call timed out.", eval_id)
    except Exception as e:  # noqa: BLE001 - top-level handler must not leak a 500 without an eval_id
        logger.exception("Unhandled error evaluating request")
        _result_log.write(error_result_log_record(eval_id, request_model.model_dump(), "internal_error", str(e)))
        return _error_body(500, "internal_error", str(e), eval_id)

    return JSONResponse(status_code=200, content=response_model.model_dump())
