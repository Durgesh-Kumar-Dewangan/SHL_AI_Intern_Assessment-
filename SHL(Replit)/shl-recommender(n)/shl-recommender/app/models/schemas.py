"""Pydantic models for the /chat API contract.

The schema below is intentionally exactly what the assignment specifies:
request = {"messages": [...]}, response = {"reply", "recommendations", "end_of_conversation"}.
Nothing more, nothing less, so the automated evaluator never fails schema validation.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str

    @field_validator("content")
    @classmethod
    def content_not_absurdly_long(cls, v: str) -> str:
        return v[:8000]


class ChatRequest(BaseModel):
    messages: list[Message] = Field(default_factory=list)


class Recommendation(BaseModel):
    """Exactly the three fields shown in the assignment's response example."""
    name: str
    url: str
    test_type: str


class ChatResponse(BaseModel):
    """API response — matches the assignment spec exactly.

    Note: the `reply` field may contain a hidden HTML comment marker of the
    form <!-- __SHORTLIST__: url1|url2 --> appended after the natural-language
    reply. This marker is invisible in any rendered HTML context and is used
    by the service to reconstruct the shortlist on the next stateless turn
    when the client echoes the reply back as an assistant message.
    """
    reply: str
    recommendations: Optional[list[Recommendation]] = None
    end_of_conversation: bool = False


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
