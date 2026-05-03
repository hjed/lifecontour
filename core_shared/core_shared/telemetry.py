"""
OpenTelemetry instrumentation setup for Personal Management System.
"""

from typing import Any

import structlog

_TELEMETRY_SETUP_DONE = False


def setup_telemetry(settings: Any, app: Any | None = None) -> None:
    """Setup OpenTelemetry instrumentation."""
    global _TELEMETRY_SETUP_DONE
    if not getattr(settings, "enable_telemetry", False):
        return

    import logging

    from opentelemetry import trace
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import (
        OTLPLogExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import (
        BatchLogRecordProcessor as LogBatchProcessor,
    )
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    logger = structlog.get_logger()

    if not _TELEMETRY_SETUP_DONE:
        # Configure resource attributes
        service_name = getattr(settings, "otel_service_name", "unknown-service")
        resource_attrs = {"service.name": service_name}

        otel_resource_attributes = getattr(settings, "otel_resource_attributes", None)
        if otel_resource_attributes:
            # Parse additional resource attributes
            for attr in otel_resource_attributes.split(","):
                if "=" in attr:
                    key, value = attr.strip().split("=", 1)
                    resource_attrs[key.strip()] = value.strip()

        # Set up tracer provider
        resource = Resource.create(resource_attrs)
        trace.set_tracer_provider(TracerProvider(resource=resource))

        # Set up logger provider
        logger_provider = LoggerProvider(resource=resource)
        set_logger_provider(logger_provider)

        # Configure OTLP exporter if endpoint is provided
        otel_exporter_otlp_endpoint = getattr(
            settings, "otel_exporter_otlp_endpoint", None
        )
        if otel_exporter_otlp_endpoint:
            otlp_exporter = OTLPSpanExporter(
                endpoint=f"{otel_exporter_otlp_endpoint}/v1/traces"
            )
            span_processor = BatchSpanProcessor(otlp_exporter)
            tracer_provider = trace.get_tracer_provider()
            if hasattr(tracer_provider, "add_span_processor"):
                tracer_provider.add_span_processor(span_processor)

            otlp_log_exporter = OTLPLogExporter(
                endpoint=f"{otel_exporter_otlp_endpoint}/v1/logs"
            )
            logger_provider.add_log_record_processor(
                LogBatchProcessor(otlp_log_exporter)
            )

            if not any(
                isinstance(h, LoggingHandler) for h in logging.getLogger().handlers
            ):
                handler = LoggingHandler(
                    level=logging.NOTSET, logger_provider=logger_provider
                )
                logging.getLogger().addHandler(handler)

        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
        except ImportError:
            logger.debug("HTTPX instrumentation not available")

        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            SQLAlchemyInstrumentor().instrument()
        except ImportError:
            logger.debug("SQLAlchemy instrumentation not available")

        try:
            from opentelemetry.instrumentation.redis import RedisInstrumentor

            RedisInstrumentor().instrument()
        except ImportError:
            logger.debug("Redis instrumentation not available")

        _TELEMETRY_SETUP_DONE = True

    # Instrument FastAPI
    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(
                app, tracer_provider=trace.get_tracer_provider()
            )
        except ImportError:
            logger.debug("FastAPI instrumentation not available")

    logger.info(
        "OpenTelemetry instrumentation enabled",
        service_name=getattr(settings, "otel_service_name", "unknown-service"),
        endpoint=getattr(settings, "otel_exporter_otlp_endpoint", None),
    )
