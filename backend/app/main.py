"""
Personal CRM & Journal System - FastAPI Backend

Main application entry point with FastAPI configuration,
middleware setup, and route registration.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

from app.api.health import router as health_router
from app.api.search.controllers import router as search_router
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.database import get_database_engine
from app.infrastructure.events.outbox_processor import run_outbox_processor_loop
from app.infrastructure.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown events."""
    settings = get_settings()
    logger = structlog.get_logger()

    # Setup logging
    setup_logging(settings.log_level)
    logger.info("Starting Personal Management System Backend", version="0.1.0")

    # Initialize database
    engine = get_database_engine()
    logger.info("Database engine initialized")

    # Setup OpenTelemetry instrumentation
    if settings.enable_telemetry:
        tracer = trace.get_tracer(__name__)
        FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer)
        HTTPXClientInstrumentor().instrument()
        SQLAlchemyInstrumentor().instrument(engine=engine)
        logger.info("OpenTelemetry instrumentation enabled")

    # Start background tasks
    outbox_task = None
    try:
        # Start outbox processor background task
        outbox_task = asyncio.create_task(
            run_outbox_processor_loop(interval_seconds=10)
        )
        logger.info("Outbox processor background task started")

        yield

    finally:
        # Cleanup background tasks
        if outbox_task:
            outbox_task.cancel()
            try:
                await outbox_task
            except asyncio.CancelledError:
                pass
            logger.info("Outbox processor background task stopped")

        logger.info("Shutting down Personal Management System Backend")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="Personal CRM & Journal System",
        description="A personal relationship management and journaling system with AI integration",
        version="0.1.0",
        docs_url="/api/docs" if settings.debug else None,
        redoc_url="/api/redoc" if settings.debug else None,
        openapi_url="/api/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    # Security middleware
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.allowed_hosts,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health_router, prefix="/api", tags=["health"])
    app.include_router(search_router, prefix="/api", tags=["search"])

    return app


# Create the application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
