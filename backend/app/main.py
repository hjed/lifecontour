"""
Personal CRM & Journal System - FastAPI Backend

Main application entry point with FastAPI configuration,
middleware setup, and route registration.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from starlette.middleware.sessions import SessionMiddleware

from app.infrastructure.config import Settings, get_settings
from app.infrastructure.database import get_database_engine
from app.infrastructure.di.container import create_container
from app.infrastructure.events.outbox_processor import run_outbox_processor_loop
from app.infrastructure.logging import setup_logging
from app.mcp.server import create_mcp_app


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

    # Setup Dishka container (get from app state)
    container = app.state.dishka_container
    logger.info("Dishka container initialized")

    # Setup OpenTelemetry instrumentation
    if settings.enable_telemetry:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        # Configure resource attributes
        resource_attrs = {"service.name": settings.otel_service_name}
        if settings.otel_resource_attributes:
            # Parse additional resource attributes
            for attr in settings.otel_resource_attributes.split(","):
                if "=" in attr:
                    key, value = attr.strip().split("=", 1)
                    resource_attrs[key] = value

        # Set up tracer provider
        resource = Resource.create(resource_attrs)
        trace.set_tracer_provider(TracerProvider(resource=resource))

        # Configure OTLP exporter if endpoint is provided
        if settings.otel_exporter_otlp_endpoint:
            otlp_exporter = OTLPSpanExporter(
                endpoint=f"{settings.otel_exporter_otlp_endpoint}/v1/traces"
            )
            span_processor = BatchSpanProcessor(otlp_exporter)
            tracer_provider = trace.get_tracer_provider()
            if hasattr(tracer_provider, "add_span_processor"):
                tracer_provider.add_span_processor(span_processor)

        # Instrument FastAPI, HTTP clients, and SQLAlchemy
        FastAPIInstrumentor.instrument_app(
            app, tracer_provider=trace.get_tracer_provider()
        )
        HTTPXClientInstrumentor().instrument()
        SQLAlchemyInstrumentor().instrument(engine=engine)

        logger.info(
            "OpenTelemetry instrumentation enabled",
            service_name=settings.otel_service_name,
            endpoint=settings.otel_exporter_otlp_endpoint,
        )

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

        # Close Dishka container
        await container.close()
        logger.info("Dishka container closed")

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

    # Setup Dishka dependency injection
    container = create_container(settings)
    app.state.dishka_container = container  # Store for lifespan access
    setup_dishka(container, app)

    # Import routers after Dishka setup to avoid type annotation issues
    from app.api.auth.controllers import router as auth_router
    from app.api.contacts.controllers import router as contacts_router
    from app.api.error_handlers import register_error_handlers
    from app.api.health import router as health_router
    from app.api.search.controllers import router as search_router
    from app.api.tags.controllers import router as tags_router

    # Session middleware (must be added before other middleware that uses sessions)
    # Using standard Starlette SessionMiddleware
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret_key,
        max_age=86400 * 7,  # 7 days
        same_site="lax",
        https_only=not settings.debug,
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

    register_error_handlers(app)

    # Include routers
    app.include_router(health_router, prefix="/api", tags=["health"])
    app.include_router(auth_router, prefix="/api/auth", tags=["authentication"])
    app.include_router(search_router, prefix="/api", tags=["search"])
    app.include_router(contacts_router, prefix="/api", tags=["contacts"])
    app.include_router(tags_router, prefix="/api", tags=["tags"])

    # Mount MCP server if enabled
    if settings.mcp_enabled:
        logger = structlog.get_logger()
        logger.info("MCP: Mounting MCP server", mount_path=settings.mcp_mount_path)

        mcp_app = create_mcp_app(container, disable_auth=settings.disable_auth)
        app.mount(settings.mcp_mount_path, mcp_app)  # type: ignore[arg-type]

        logger.info(
            "MCP: Server mounted successfully",
            endpoint=f"{settings.mcp_mount_path}/mcp",
        )

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
