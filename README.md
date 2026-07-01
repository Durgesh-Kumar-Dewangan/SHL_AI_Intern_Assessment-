## Assignment Details: Build a Conversational SHL Assessment Recommender

---
title: SHL Assessment Recommender
emoji: 🎯
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Conversational SHL assessment recommender with BM25 retrieval and web UI
---

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
cd shl-assessment-recommender
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set LLM_PROVIDER + LLM_API_KEY (see .env.example for free-tier options)

uvicorn app.main:app --reload --port 8080
```

Open **http://localhost:8080** in your browser for the web UI (chat, catalog
browser, compare tool, API explorer). Or use the API directly:

```bash
curl http://localhost:8080/health
# {"status":"ok"}

curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hiring a mid-level Java developer who works with stakeholders"}]}'
```

> **Note:** If port 8080 is busy, use any free port. The UI and API share the
> same origin, so static assets and `/chat` always stay in sync.

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
├── api/index.py                 Vercel serverless entrypoint
├── app/
│   ├── main.py                  FastAPI app + lifespan (index warm-up)
│   ├── config.py                Pydantic Settings (env-var driven)
│   ├── dependencies.py          FastAPI dependency injection (catalog, LLM, service)
│   ├── api/routes.py            /health, /chat, /catalog, UI routes
│   ├── static/                  Web UI (HTML, CSS, JS)
│   ├── data/shl_catalog.json    377 normalized catalog items
│   ├── retrieval/retriever.py   BM25 hybrid retriever
│   └── services/                conversation, LLM client, safety (injection filter)
├── tests/                       34 pytest tests
├── Dockerfile                   Hugging Face Spaces + Docker deploy
├── vercel.json                  Vercel deploy config
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

### Hugging Face Spaces

1. Create a new Space at [huggingface.co/new-space](https://huggingface.co/new-space)
   and choose **Docker** as the SDK.
2. Push this repo (root contains `Dockerfile` and `README.md` frontmatter).
3. In Space **Settings → Variables and secrets**, add:
   - `LLM_API_KEY` — your Groq/Gemini/OpenAI key (required for chat)
   - `LLM_PROVIDER` — e.g. `groq` (optional)
   - `LLM_MODEL` — e.g. `llama-3.3-70b-versatile` (optional)
4. The Space builds from `Dockerfile` and serves the UI on port **7860**.

### Vercel

1. Import this repo at [vercel.com/new](https://vercel.com/new).
2. Framework preset: **Other** (uses `vercel.json` + `api/index.py`).
3. Add environment variables in the Vercel dashboard:
   - `LLM_API_KEY`, `LLM_PROVIDER`, `LLM_MODEL`
4. Deploy — the FastAPI app serves both the API and web UI.

Alternatively, configure the LLM key from the in-app **Settings** panel once
deployed (no rebuild needed).

**Docker (local or any host)**:
```bash
docker build -t shl-recommender .
docker run -p 7860:7860 --env-file .env shl-recommender
# UI: http://localhost:7860
```

Cold-start note: the catalog + BM25 index is loaded/built once at process
startup (`app/main.py` lifespan), not per-request, so even a cold free-tier
dyno only pays that cost once.
