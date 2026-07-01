# Approach Document

## Problem framing
The core difficulty isn't retrieval accuracy so much as **conversation control**:
deciding, on every turn, whether to ask, retrieve+recommend, refine in place,
compare, or refuse -- statelessly, within an 8-turn/30s budget. I optimized
for that decision quality over infrastructure sophistication.

## Architecture
```
FastAPI (/health, /chat)
  -> Safety pre-filter (deterministic regex: injection, off-topic)
  -> Retriever (BM25 hybrid + metadata filters + name-match boosting)
  -> LLM (single call/turn: system prompt + retrieved candidates + full history)
  -> Grounding verification (drop any URL not exactly in the catalog)
  -> Turn-cap safety net (force-resolve on the last allowed turn)
```
A single well-scoped LLM call per turn, not a multi-agent LangGraph pipeline.
Given the 30s/call and 8-turn budget, each additional agent hop is latency and
failure surface with no proportional quality gain for a conversation this
short. The system prompt encodes all four behaviors (clarify/recommend/
refine/compare) and I found one strong prompt outperformed several weaker,
narrowly-scoped ones in manual testing -- it has full context every time
instead of losing information across hand-offs. The codebase is still
modular (retriever, safety, LLM client, prompt builder, orchestration are
separate, independently testable modules) so swapping in a graph-based
orchestrator later is a contained change, not a rewrite.

## Retrieval: BM25 over dense embeddings
I chose `rank_bm25` (keyword/BM25) over sentence-transformers + FAISS. For a
377-item, short, well-described catalog, BM25 is a strong baseline, and it
avoids downloading a large embedding model on every cold start of a
free-tier host -- which risked blowing the 30s per-call budget on the first
request after a scale-to-zero. I supplement BM25 with: (1) synonym expansion
for recruiter vocabulary ("cognitive" -> "verify/ability/aptitude"), (2)
exact/partial product-name boosting so "OPQ32r" ranks its own product highly
even if BM25's term weighting wouldn't, and (3) metadata filters
(duration/remote/adaptive) parsed from simple patterns in the user's text.
Top-20 candidates are handed to the LLM as the *only* legal source of
recommendations -- retrieval recall, not precision, is what matters at this
stage, since the LLM does the final ranking/selection.

**Tradeoff acknowledged**: BM25 will underperform semantic search on queries
using vocabulary far from the catalog's own (e.g. a JD paragraph with no
direct keyword overlap). The synonym table and name-boosting close some of
this gap; a proper fix would be a lightweight local embedding model (e.g.
`all-MiniLM-L6-v2` via ONNX, no torch) if bundle size / cold-start allowed it.

## Grounding & hallucination control
Two independent layers: the prompt instructs the LLM that
`CANDIDATE_ASSESSMENTS` is the only legal source and every URL must be copied
verbatim; the code then re-verifies every returned URL against the real
catalog and silently drops anything that doesn't match exactly (logged as a
warning). If grounding fails entirely for a "recommend" turn, the service
degrades to a clarifying question rather than returning an empty or garbage
shortlist. This means a hallucinated URL literally cannot reach the response,
regardless of what the LLM outputs.

## Statelessness and the "refine" behavior
The API stores nothing between calls. To make "add personality tests" work
without restarting the shortlist, the *full* prior conversation (including
all earlier user constraints) is always resent by the client and passed to
the LLM verbatim -- the model naturally has everything it needs. As a second
signal, I scan the assistant's own most recent reply for catalog product-name
mentions to reconstruct an explicit `CURRENT_SHORTLIST_URLS` hint, which
keeps refinement anchored even if a user's message references "it" or "the
list" without repeating specifics.

## Safety
Prompt injection and off-topic requests (legal, medical, general hiring
advice, programming help) are caught by a **deterministic regex pre-filter**
before the LLM is ever called, in addition to prompt-level instructions. I
did this because relying on the LLM alone to resist injection is exactly the
failure mode injection attacks target -- a cheap, fast, non-LLM layer that
can't be argued with is a meaningfully stronger guarantee for the highest-risk
category (the "ignore previous instructions" family).

## Evaluation
- **Unit/integration tests** (`tests/`, 34 tests, no LLM key required -- the
  LLM boundary is mocked): schema compliance, recommendation-count bounds
  (1-10), URL groundedness, turn-cap forcing, safety-filter categories,
  retriever correctness (relevance, metadata filters, dedup).
- **Trace replay harness** (`eval/run_eval.py`): parses the 10 provided
  markdown traces, replays their literal user turns against a live `/chat`
  endpoint, and computes Recall@10 against each trace's labeled final
  shortlist, plus a small battery of behavior probes (injection, off-topic,
  no-recommendation-on-vague-turn-1).

## What didn't work / what I'd improve with more time
- An early version tried to have the LLM emit the *entire* markdown table
  (name, type, duration, languages, URL) as part of `reply`. This
  occasionally drifted from the retrieved candidate data (e.g. slightly
  wrong duration) because the model was regenerating facts from its own
  memory of SHL products instead of copying the provided JSON. Fix: the LLM
  now only returns `reply` text + a list of URLs; the API constructs
  `Recommendation` objects (name, url, test_type) directly from the catalog
  record for that URL, so those fields can never drift from ground truth.
- Pure BM25 initially missed some JD-paragraph-style queries with no keyword
  overlap (e.g. a full job description with no product-name-adjacent terms).
  Query expansion using the last 4 user turns (not just the latest message)
  and the synonym table recovered most of this without adding embedding
  infrastructure.
- I considered forcing `end_of_conversation=true` immediately whenever a
  shortlist is first presented, but the traces show real refinement continues
  after a first shortlist (e.g. "actually add personality tests"), so ending
  early would break the refine behavior; the LLM now only ends after an
  explicit confirmation, with a turn-cap fallback as a backstop.

## AI-tool usage disclosure
This solution was built with Claude as an AI pair-programmer: used to
scaffold boilerplate (Pydantic models, FastAPI wiring, test skeletons) and to
iterate on the system prompt, with retrieval scoring, grounding-verification
logic, and safety patterns hand-reviewed and adjusted against the provided
traces. All design tradeoffs above reflect deliberate decisions that can be
walked through in a technical deep-dive.
