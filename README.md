# FAQ RAG Evaluation Service

Scores how well a Cognigy AI Agent answered a customer's FAQ question, using the
[Ragas](https://github.com/explodinggradients/ragas) library and an LLM judge.
Built from the spec in `../cognigy-ragas-faq-evaluation.md` (section 6).

## What it does

Cognigy's flow captures a question, what the agent retrieved from the knowledge
base, and the agent's answer — then sends all three to this service. The
service:

1. **Classifies** the response as `ANSWER`, `CLARIFY`, or `DECLINE` (an LLM
   judge call, not a keyword check — answers often end in a question too,
   e.g. "Anything else I can help with?").
2. **Matches** the question against a 60-entry golden set of reference
   Q&As (embedding similarity shortlist → LLM picks the best match, or
   `none`). This runs for every response, since even clarifications and
   declines are graded against what the golden set says *should* have
   happened.
3. **Scores** up to five Ragas metrics, depending on the case (see below):
   `faithfulness`, `factual_correctness`, `response_relevancy`,
   `context_recall`, `context_precision`.
4. **Applies thresholds** to turn those scores into three pass/fail
   outcomes: `accurate` (was the answer right), `retrieval` (did search
   find the right info), `relevant` (did it address the question).
5. **Logs** the full detail (request, scores, reasoning, timings) to a
   local JSON Lines file, keyed by `session_id` + `input_id`.

It's a single endpoint: `POST /evaluate`. No state is kept between calls
except the golden set and the five Ragas metric objects, which are loaded
once at startup.

## Why classify before scoring

A clarifying question or a decline isn't a wrong "answer" — it just isn't an
answer at all. Scoring it against the reference answer's wording would
always fail. So the service decides *what kind of response this is* first,
then only runs the metrics that make sense for that case. There are nine
such cases in total (`app/outcomes.py` — see the docstring there for the
one edge case worth knowing about: an agent that answers a question it
should have declined gets a `response_relevancy` score computed and
returned, but that score isn't used to set the `relevant` outcome, matching
the spec's table literally).

## Request / response shape

```jsonc
// POST /evaluate
{
  "session_id": "sess-1",
  "input_id": "turn-4",
  "run_id": "2026-10-01-r1",
  "user_message": "what about scuba on that plan?",
  "standalone_query": "Does Travel Plus cover scuba diving",
  "recent_turns": [{ "role": "user", "text": "..." }],
  "response": "Travel Plus does not cover scuba diving...",
  "retrieved_contexts": [
    { "chunk_id": "KB-TRV-003-01", "source_id": "KB-TRV-003", "text": "...", "rank": 1 }
  ]
}
```

```jsonc
// 200 OK
{
  "eval_id": "uuid",
  "golden_set_version": "gs-v1",
  "classification": "ANSWER",
  "match": { "reference_id": "FAQ-022", "confidence": 0.91, "expected_classification": "ANSWER", "candidates": [...] },
  "scores": { "faithfulness": 1.0, "factual_correctness": 0.67, "response_relevancy": 0.88, "context_recall": 0.67, "context_precision": 0.83 },
  "outcomes": { "accurate": "fail", "retrieval": "fail", "relevant": "pass" },
  "retrieval_check": { "expected_chunk_ids": [...], "retrieved_expected": 1 },
  "ragas_version": "0.3.9",
  "judge_model": "gpt-4.1"
}
```

### Async mode (`writeback: true`) — used by Cognigy

Cognigy's HTTP service gives up after a hard **15s**, and a full evaluation
regularly takes 10–25s. So Cognigy calls in async mode: add three fields to
the request above.

```jsonc
{
  // ...same fields as above, plus:
  "writeback": true,
  "contact_id": "{{ci.userId}}",
  "project_id": "6ab9d449a3709e53b89767da"
}
```

```jsonc
// 202 Accepted, returned in ~0.1s
{ "eval_id": "uuid", "status": "accepted" }
```

The service then scores in the background and writes `custom1`–`custom10`
onto that turn's Cognigy analytics record with `PATCH /v2.0/analytics`
(`app/cognigy_analytics.py`). `contact_id` is the plain Cognigy userId;
the service MD5-hashes it, because that's how Cognigy stores `contactId` on
analytics records. The PATCH merges, so other fields on the
record are untouched. It retries on 400/404/5xx/network errors (2s, 5s, 10s,
20s) in case the record hasn't been written yet. If the eval itself fails,
it still PATCHes `custom9 = A:error|R:error|V:error` and
`custom10 = <run_id>|error-<code>`. Every write-back attempt is logged as a
`"type": "writeback"` line in the result log, with the final status.

Ragas usage telemetry is switched off (`RAGAS_DO_NOT_TRACK=true`, set in
`app/config.py`). It sends a blocking HTTP request on every Ragas LLM and
embedding call, which stalled the whole server while a background eval ran
and roughly doubled eval time.

Needs `COGNIGY_API_BASE_URL` and `COGNIGY_API_KEY` set; without them a
`writeback: true` call returns `500` `config`. Without `writeback` the
service behaves exactly as before (sync, `200`).

Full contract: `../cognigy-ragas-faq-evaluation.md` section 6.2.
Errors come back as `{ "error": "code", "message": "...", "eval_id": "uuid" }`
with status `400` (bad payload), `401` (bad `X-API-Key`), `500` (internal),
or `504` (judge LLM timed out).

## Project layout

| Path | Purpose |
|---|---|
| `main.py` | FastAPI app — the `/evaluate` and `/health` HTTP endpoints |
| `app/classification.py` | ANSWER / CLARIFY / DECLINE judge call |
| `app/matching.py` | Embedding shortlist + judge pick against the golden set |
| `app/outcomes.py` | The 9-case decision table: which metrics to run, pass/fail rules |
| `app/metrics.py` | Builds and runs the 5 Ragas metrics |
| `app/retrieval_check.py` | Deterministic chunk-ID overlap check (not an LLM call) |
| `app/golden_set.py` | Loads the golden set + its precomputed question embeddings |
| `app/llm_clients.py` | OpenAI chat + embedding clients, wrapped for Ragas |
| `app/result_log.py` | Appends one JSON record per evaluation |
| `app/cognigy_analytics.py` | Async mode: PATCHes results onto the Cognigy analytics record |
| `app/evaluate.py` | Orchestrates the above into one pipeline |
| `data/` | Bundled copy of the golden set + its embedding cache, for deployment |
| `scripts/precompute_golden_set_embeddings.py` | Rebuilds `data/golden_set.embeddings.json` after the golden set changes |
| `tests/` | 40 unit tests — everything except live Ragas metric scoring is tested with fakes (no OpenAI key needed) |

## Running it locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # then fill in OPENAI_API_KEY and API_KEY yourself
uvicorn main:app --reload
```

```bash
curl -X POST http://localhost:8000/evaluate \
  -H "X-API-Key: <your API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "t", "input_id": "1", "run_id": "r1", "user_message": "...", "standalone_query": "...", "response": "...", "retrieved_contexts": []}'
```

Run the test suite (no OpenAI key required):

```bash
python3 -m pytest -q
```

## Deployment

Hosted on Railway as a plain Python process (`Procfile` / `railway.json`).
Set `OPENAI_API_KEY`, `API_KEY`, `COGNIGY_API_BASE_URL` and
`COGNIGY_API_KEY` in the host's dashboard — nothing secret
ships in the code. The golden set and its embeddings are bundled under
`data/`, so no external file or database is needed at runtime. If the
golden set changes, re-run `scripts/precompute_golden_set_embeddings.py`
and redeploy with the refreshed `data/golden_set.embeddings.json`.

## What this doesn't do

- Only talks to Cognigy in async mode, and only to PATCH the analytics
  record for the turn it was given. Cognigy's flow calls this service's
  `POST /evaluate` over plain HTTP (spec section 5).
- Doesn't store results anywhere queryable yet — the result log is a flat
  JSON Lines file (`LOG_DESTINATION`); Azure Table Storage was the original
  proposal but isn't implemented (`app/result_log.py` raises clearly if
  you point `LOG_DESTINATION` at `table:`).
- Doesn't calibrate thresholds — the five starting thresholds
  (`app/config.py`) are the spec's initial guesses, meant to be revisited
  after the first real run (spec section 10).
