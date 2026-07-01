from __future__ import annotations

import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import get_settings
from app.dependencies import get_retriever, shutdown
from app.utils.logging import configure_logging

STATIC_DIR = pathlib.Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    # Warm the catalog + retriever index at startup (fast: 377 short docs) so the
    # first real request isn't paying BM25 index-build latency.
    get_retriever()
    yield
    await shutdown()


app = FastAPI(
    title="SHL Assessment Recommender",
    description="Conversational agent that recommends SHL Individual Test Solutions.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static UI files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(router)
