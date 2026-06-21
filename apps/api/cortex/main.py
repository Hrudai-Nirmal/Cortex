"""FastAPI application factory with explicit middleware and domain error boundaries."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cortex.api.routes import router
from cortex.logging_config import configureLogging


def createApp() -> FastAPI:
    """Create the Cortex API without performing network operations at import time."""
    configureLogging()
    application = FastAPI(
        title="Cortex API",
        version="0.1.0",
        description="Evidence-bounded enterprise RAG control plane",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Cortex-Enterprise"],
    )
    application.include_router(router)
    return application


app = createApp()
