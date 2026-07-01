"""API contract tests: health check + /chat schema compliance."""
from __future__ import annotations


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_chat_empty_messages(client):
    r = client.post("/chat", json={"messages": []})
    assert r.status_code == 200
    body = r.json()
    assert "reply" in body and "recommendations" in body and "end_of_conversation" in body
    assert body["recommendations"] is None
    assert body["end_of_conversation"] is False


def test_chat_response_schema_on_recommend(client, mock_llm):
    with mock_llm(action="recommend", n=3):
        r = client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "Hiring a senior backend Java developer, 5 years, Spring/SQL"}]},
        )
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"reply", "recommendations", "end_of_conversation"}
    assert isinstance(body["reply"], str) and body["reply"]
    assert isinstance(body["recommendations"], list)
    assert 1 <= len(body["recommendations"]) <= 10
    for rec in body["recommendations"]:
        assert set(rec.keys()) == {"name", "url", "test_type"}
        assert rec["url"].startswith("https://www.shl.com/")


def test_chat_response_schema_on_clarify(client, mock_llm):
    with mock_llm(action="clarify"):
        r = client.post("/chat", json={"messages": [{"role": "user", "content": "We need an assessment"}]})
    assert r.status_code == 200
    body = r.json()
    assert body["recommendations"] is None
    assert body["end_of_conversation"] is False


def test_recommendations_never_exceed_ten(client, mock_llm):
    with mock_llm(action="recommend", n=25):
        r = client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "Full battery for graduate management trainees: cognitive, personality, SJT"}]},
        )
    body = r.json()
    assert len(body["recommendations"]) <= 10


def test_all_recommendation_urls_are_grounded_in_catalog(client, mock_llm):
    """Every returned URL must exist in the real scraped catalog -- never invented."""
    from app.dependencies import get_retriever

    retriever = get_retriever()
    known_urls = {i.url for i in retriever.items}

    with mock_llm(action="recommend", n=5):
        r = client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "Entry level customer service contact center screening"}]},
        )
    body = r.json()
    for rec in body["recommendations"]:
        assert rec["url"] in known_urls


def test_turn_cap_forces_resolution(client, mock_llm):
    """At the 8-turn cap, the agent must not still be asking clarifying questions
    forever -- it should resolve to a shortlist (hard eval: turn cap honored)."""
    messages = []
    for i in range(3):
        messages.append({"role": "user", "content": f"Some vague hiring need number {i}"})
        messages.append({"role": "assistant", "content": "Could you clarify further?"})
    messages.append({"role": "user", "content": "Java developer, mid-level, Spring and SQL"})

    with mock_llm(action="clarify"):
        r = client.post("/chat", json={"messages": messages})
    body = r.json()
    # 7 messages already + this reply = 8th message -> must resolve to a shortlist.
    assert body["recommendations"] is not None
    assert body["end_of_conversation"] is True
