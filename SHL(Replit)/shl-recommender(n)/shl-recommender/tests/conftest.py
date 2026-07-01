from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.llm_client import LLMClient


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def make_fake_llm(action: str = "recommend", n: int = 3, end: bool = False, reply: str = "Here is your shortlist."):
    """Builds a fake `complete_json` coroutine that recommends the first `n`
    candidates handed to it. Used to test the pipeline deterministically
    without calling a real LLM provider."""

    async def _fake(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = json.loads(user_prompt.split("Respond with the JSON object only.\n\n", 1)[1])
        cands = payload["CANDIDATE_ASSESSMENTS"]
        urls = [c["url"] for c in cands[:n]] if action == "recommend" else []
        return {
            "action": action,
            "reply": reply,
            "recommended_urls": urls,
            "end_of_conversation": end,
        }

    return _fake


@pytest.fixture()
def mock_llm():
    def _apply(action: str = "recommend", n: int = 3, end: bool = False, reply: str = "Here is your shortlist."):
        return patch.object(LLMClient, "complete_json", make_fake_llm(action, n, end, reply))

    return _apply
