"""Application-scoped singletons, wired once at startup and injected into routes.

Keeping this separate from main.py keeps FastAPI route handlers thin and
makes the pieces (catalog, retriever, LLM client) independently testable.
"""
from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.data.catalog_loader import load_catalog
from app.retrieval.retriever import Retriever
from app.services.conversation_service import ConversationService
from app.services.llm_client import LLMClient


@lru_cache
def get_retriever() -> Retriever:
    settings = get_settings()
    items = load_catalog(settings.catalog_path)
    return Retriever(items)


_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient(get_settings())
    return _llm_client


def get_conversation_service() -> ConversationService:
    settings: Settings = get_settings()
    return ConversationService(retriever=get_retriever(), llm_client=get_llm_client(), settings=settings)


async def refresh_llm_client() -> None:
    global _llm_client
    if _llm_client is not None:
        await _llm_client.aclose()
    _llm_client = LLMClient(get_settings())


async def shutdown() -> None:
    global _llm_client
    if _llm_client is not None:
        await _llm_client.aclose()
        _llm_client = None
