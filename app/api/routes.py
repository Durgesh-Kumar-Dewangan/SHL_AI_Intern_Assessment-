from __future__ import annotations

import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app.dependencies import get_conversation_service, get_retriever, refresh_llm_client
from app.models.schemas import ChatRequest, ChatResponse, HealthResponse
from app.retrieval.retriever import Retriever
from app.services.conversation_service import ConversationService
from app.config import get_settings

logger = logging.getLogger("shl_recommender.api")

router = APIRouter()


@router.get("/", include_in_schema=False)
async def root():
    import pathlib
    return FileResponse(pathlib.Path(__file__).parent.parent / "static" / "index.html")


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    from fastapi.responses import Response
    # Return a minimal valid ICO (1x1 transparent pixel)
    ico = (
        b"\x00\x00\x01\x00\x01\x00\x01\x01\x00\x00\x01\x00\x18\x00"
        b"\x30\x00\x00\x00\x16\x00\x00\x00\x28\x00\x00\x00\x01\x00"
        b"\x00\x00\x02\x00\x00\x00\x01\x00\x18\x00\x00\x00\x00\x00"
        b"\x04\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x1d\x4e\xd8\x00\x00\x00\x00\x00"
    )
    return Response(content=ico, media_type="image/x-icon")


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> ChatResponse:
    start = time.perf_counter()
    response = await service.handle_chat(request.messages)
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        "chat_turn_completed",
        extra={
            "extra_fields": {
                "latency_ms": latency_ms,
                "num_messages": len(request.messages),
                "num_recommendations": len(response.recommendations) if response.recommendations else 0,
                "end_of_conversation": response.end_of_conversation,
            }
        },
    )
    return response


@router.get("/admin/settings", include_in_schema=False)
async def admin_get_settings():
    s = get_settings()
    return {
        "llm_provider": s.llm_provider,
        "llm_model": s.llm_model,
        "llm_api_key_set": bool(s.llm_api_key),
        "llm_temperature": s.llm_temperature,
        "llm_max_tokens": s.llm_max_tokens,
    }


@router.post("/admin/settings", include_in_schema=False)
async def admin_update_settings(payload: dict):
    if "llm_provider" in payload and payload["llm_provider"]:
        os.environ["LLM_PROVIDER"] = str(payload["llm_provider"])
    if "llm_model" in payload and payload["llm_model"]:
        os.environ["LLM_MODEL"] = str(payload["llm_model"])
    if "llm_api_key" in payload and payload["llm_api_key"]:
        os.environ["LLM_API_KEY"] = str(payload["llm_api_key"])
    if "llm_temperature" in payload and payload["llm_temperature"] is not None:
        os.environ["LLM_TEMPERATURE"] = str(payload["llm_temperature"])
    if "llm_max_tokens" in payload and payload["llm_max_tokens"] is not None:
        os.environ["LLM_MAX_TOKENS"] = str(payload["llm_max_tokens"])
    get_settings.cache_clear()
    await refresh_llm_client()
    s = get_settings()
    return {"ok": True, "llm_provider": s.llm_provider, "llm_model": s.llm_model}


@router.get("/catalog")
async def catalog(
    q: Optional[str] = Query(None, description="Search query"),
    type: Optional[str] = Query(None, description="Test type code filter (A, B, C, K, P, S)"),
    limit: int = Query(50, ge=1, le=400),
    retriever: Retriever = Depends(get_retriever),
):
    """Return catalog items, optionally filtered by search query and/or test type."""
    settings = get_settings()
    items = retriever.items

    if q and q.strip():
        scored = retriever.search(q, top_k=limit)
        items = [s.item for s in scored]
    elif type:
        items = [i for i in items if type in i.test_type_codes]

    if type and q:
        items = [i for i in items if type in i.test_type_codes]

    items = items[:limit]

    return {
        "total": len(retriever.items),
        "returned": len(items),
        "model": f"{settings.llm_provider} / {settings.llm_model}",
        "items": [
            {
                "id": item.id,
                "name": item.name,
                "url": item.url,
                "description": item.description[:300] if item.description else "",
                "duration_display": item.duration_display,
                "duration_minutes": item.duration_minutes,
                "test_type": item.test_type,
                "test_type_codes": list(item.test_type_codes),
                "adaptive": item.adaptive,
                "remote_testing": item.remote_testing,
                "job_levels": list(item.job_levels),
                "languages": list(item.languages[:5]),
            }
            for item in items
        ],
    }
