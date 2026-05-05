from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core_shared.telemetry import trace_arq_job


@pytest.mark.asyncio
async def test_trace_arq_job_decorator_extracts_context_and_starts_span() -> None:
    # Setup mock telemetry setup done to True to trigger tracing logic
    import core_shared.telemetry

    original_setup_done = core_shared.telemetry._TELEMETRY_SETUP_DONE
    core_shared.telemetry._TELEMETRY_SETUP_DONE = True

    try:
        with (
            patch("opentelemetry.trace.get_tracer") as mock_get_tracer,
            patch("opentelemetry.propagate.extract") as mock_extract,
        ):
            mock_tracer = MagicMock()
            mock_get_tracer.return_value = mock_tracer

            mock_span_context_manager = MagicMock()
            mock_tracer.start_as_current_span.return_value = mock_span_context_manager

            mock_extracted_context = MagicMock()
            mock_extract.return_value = mock_extracted_context

            @trace_arq_job
            async def dummy_job(ctx: dict[str, Any], *args: Any, **kwargs: Any) -> str:
                return "success"

            ctx = {"job_id": "test-job-123", "job_name": "dummy_job"}
            otel_carrier = {"traceparent": "00-xxx-yyy-01"}

            result = await dummy_job(ctx, otel_carrier=otel_carrier)

            assert result == "success"
            mock_extract.assert_called_once_with(otel_carrier)
            mock_tracer.start_as_current_span.assert_called_once_with(
                "dummy_job",
                context=mock_extracted_context,
                attributes={
                    "messaging.message_id": "test-job-123",
                    "messaging.system": "arq",
                    "messaging.operation": "process",
                },
            )
            mock_span_context_manager.__enter__.assert_called_once()
            mock_span_context_manager.__exit__.assert_called_once()
    finally:
        core_shared.telemetry._TELEMETRY_SETUP_DONE = original_setup_done
