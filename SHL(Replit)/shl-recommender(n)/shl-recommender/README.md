# SHL Assessment Recommender

A conversational agent that helps recruiters find the right SHL **Individual
Test Solutions** through natural dialogue: it clarifies vague requests,
recommends a grounded shortlist (1-10 assessments), refines that shortlist as
constraints change, compares assessments on request, and refuses anything
outside its scope (general hiring advice, legal/medical questions, code
help, prompt injection).

Built for the SHL AI Intern take-home assignment. See `APPROACH.md` for the
2-page design write-up (retrieval choices, prompt design, evaluation, what
didn't work).

## Quick start

```bash
git clone <this-repo>
cd shl-recommender
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set LLM_PROVIDER + LLM_API_KEY (see .env.example for free-tier options)

uvicorn app.main:app --reload --port 8000
```

Then:

```bash
curl http://localhost:8000/health
# {"status":"ok"}

curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hiring a mid-level Java developer who works with stakeholders"}]}'
```

## API

### `GET /health`
Returns `{"status": "ok"}`, HTTP 200. No dependencies checked (fast, always available).

### `POST /chat`
Stateless. The full conversation history is sent on every call; the service
stores no per-conversation state.

**Request**
```json
{
  "messages": [
    {"role": "user", "content": "Hiring a Java developer who works with stakeholders"},
    {"role": "assistant", "content": "Sure. What is seniority level?"},
    {"role": "user", "content": "Mid-level, around 4 years"}
  ]
}
```

**Response**
```json
{
  "reply": "Got it. Here are 5 assessments that fit a mid-level Java dev with stakeholder needs.",
  "recommendations": [
    {"name": "Java 8 (New)", "url": "https://www.shl.com/...", "test_type": "K"},
    {"name": "Occupational Personality Questionnaire OPQ32r", "url": "https://www.shl.com/...", "test_type": "P"}
  ],
  "end_of_conversation": false
}
```

- `recommendations` is `null` while the agent is still clarifying or has
  refused; it is an array of **1-10** items once the agent has committed to a
  shortlist. Every `url` is guaranteed to come from the scraped catalog (see
  "Grounding" below).
- `end_of_conversation` is `true` only once a shortlist has been delivered
  **and** the user has confirmed it.

## Project structure

```
shl-recommender/
├── app/
│   ├── main.py                  FastAPI app + lifespan (index warm-up)
│   ├── config.py                Pydantic Settings (env-var driven, no hardcoded secrets)
│   ├── dependencies.py          Singleton wiring (catalog, retriever, LLM client)
│   ├── api/routes.py            /health, /chat
│   ├── models/schemas.py        Request/response models (exact assignment schema)
│   ├── data/
│   │   ├── catalog_loader.py    Loads shl_catalog.json into CatalogItem objects
│   │   ├── shl_catalog.json     Cleaned, normalized catalog (377 items)
│   │   └── shl_catalog.csv      Same data, CSV export
│   ├── retrieval/retriever.py   BM25 hybrid retriever + metadata filtering
│   ├── services/
│   │   ├── conversation_service.py   Orchestrates safety -> retrieval -> LLM -> grounding
│   │   ├── llm_client.py             Multi-provider async LLM adapter
│   │   └── safety.py                 Deterministic injection/off-topic pre-filter
│   ├── prompts/system_prompt.py Single grounded system prompt driving all 4 behaviors
│   └── utils/logging.py         Structured JSON logging
├── scripts/build_catalog.py     Re-runnable raw-scrape -> cleaned-catalog pipeline
├── eval/
│   ├── parse_traces.py          Parses the provided C1-C10 markdown traces
│   ├── run_eval.py              Recall@10 + behavior-probe harness against a live server
│   └── traces/                  The 10 provided conversation traces
├── tests/                       34 pytest tests: API contract, retrieval, safety, behavior probes
├── Dockerfile / docker-compose.yml
├── render.yaml / railway.json   One-click deploy configs
└── .env.example
```

## Running tests

```bash
pip install pytest
pytest -v
```

All 34 tests run **without** a real LLM key -- the LLM call is mocked at the
`LLMClient.complete_json` boundary, so the tests exercise the full pipeline
(safety filter, retrieval, grounding verification, turn-cap handling, schema
compliance) deterministically. See `tests/conftest.py`.

## Running the evaluation harness

Requires a running server (with a real `LLM_API_KEY` configured) and replays
the 10 provided conversation traces against it:

```bash
uvicorn app.main:app --port 8000 &
python -m eval.run_eval --base-url http://localhost:8000
```

Outputs `eval/eval_report.json` with mean Recall@10 across traces and a
behavior-probe pass rate (refusal of injection/off-topic/vague-turn-1
probes). See APPROACH.md for what this measured during development.

## Design highlights

- **Grounding is enforced twice**: once in the system prompt (LLM must only
  cite `CANDIDATE_ASSESSMENTS`), and again in code (`conversation_service.py`
  drops any URL the LLM returns that isn't an exact match in the catalog).
  A hallucinated URL can never reach the response.
- **Safety is a deterministic pre-filter**, not just a prompt instruction:
  prompt-injection and off-topic patterns are caught by regex *before* the
  LLM ever sees them, so a jailbreak attempt can't rely on swaying the model.
- **Stateless by construction**: nothing is cached per-conversation. The
  "current shortlist" for refine-in-place behavior is reconstructed each call
  by scanning the assistant's own prior reply (present in the client-supplied
  history) for catalog product-name mentions.
- **Turn-cap safety net**: if the conversation is on its last allowed turn and
  the agent still hasn't produced a shortlist, it force-resolves to a
  best-effort recommendation rather than risk running past the evaluator's
  8-turn cap unresolved.
- **BM25 over dense embeddings**: see APPROACH.md for the tradeoff -- for a
  377-item, well-described catalog, this keeps cold start and per-request
  latency near zero with no model download, which matters on free-tier hosts
  under a 30s per-call budget.

## Deployment

**Render**: push to a repo, "New Web Service" from `render.yaml`, set
`LLM_API_KEY` in the dashboard.

**Railway**: `railway up`, then set `LLM_API_KEY` via `railway variables set`.

**Docker**:
```bash
docker build -t shl-recommender .
docker run -p 8000:8000 --env-file .env shl-recommender
```

Cold-start note: the catalog + BM25 index is loaded/built once at process
startup (`app/main.py` lifespan), not per-request, so even a cold free-tier
dyno only pays that cost once.
