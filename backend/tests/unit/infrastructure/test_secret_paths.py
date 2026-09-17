"""Unit tests for keeping secret URL path segments out of logs and traces."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.infrastructure.secret_paths import (
    redact_secret_path_span_attributes,
    redact_secret_paths,
    redact_secret_paths_processor,
)

TOKEN = "Zm9vYmFyLXNlY3JldC10b2tlbi0wMTIzNDU2Nzg5YWJj"
WEBHOOK_PATH = f"/api/integrations/snipeit/webhook/{TOKEN}"
REDACTED_PATH = "/api/integrations/snipeit/webhook/{webhook_token}"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(WEBHOOK_PATH, REDACTED_PATH, id="path"),
        pytest.param(
            f"https://pms.example.com{WEBHOOK_PATH}?x=1",
            f"https://pms.example.com{REDACTED_PATH}?x=1",
            id="full-url",
        ),
        pytest.param(
            f"POST {WEBHOOK_PATH}/ failed",
            f"POST {REDACTED_PATH}/ failed",
            id="embedded-in-text",
        ),
        pytest.param(
            "/api/integrations/snipeit/webhook",
            "/api/integrations/snipeit/webhook",
            id="tokenless-path",
        ),
        pytest.param(
            "/api/integrations/snipeit/webhook-url",
            "/api/integrations/snipeit/webhook-url",
            id="webhook-url-endpoint",
        ),
        pytest.param("/api/journals/42", "/api/journals/42", id="unrelated-path"),
    ],
)
def test_redact_secret_paths(text: str, expected: str) -> None:
    assert redact_secret_paths(text) == expected


def test_log_processor_redacts_every_string_value() -> None:
    event_dict = {
        "event": f"Request to {WEBHOOK_PATH} failed",
        "path": WEBHOOK_PATH,
        "status_code": 400,
    }

    redacted = redact_secret_paths_processor(None, "warning", event_dict)

    assert redacted == {
        "event": f"Request to {REDACTED_PATH} failed",
        "path": REDACTED_PATH,
        "status_code": 400,
    }


@pytest.fixture
def span_exporter() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    yield exporter
    exporter.clear()


def test_span_hook_keeps_the_token_out_of_request_spans(
    span_exporter: InMemorySpanExporter,
) -> None:
    app = FastAPI()

    @app.post("/api/integrations/snipeit/webhook/{webhook_token}")
    async def webhook(webhook_token: str) -> Response:
        return Response(status_code=200)

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        server_request_hook=redact_secret_path_span_attributes,
    )
    try:
        response = TestClient(app).post(f"{WEBHOOK_PATH}?source=snipeit")
    finally:
        FastAPIInstrumentor.uninstrument_app(app)

    assert response.status_code == 200
    spans = span_exporter.get_finished_spans()
    assert spans
    attribute_values = [
        str(value) for span in spans for value in (span.attributes or {}).values()
    ]
    assert not any(TOKEN in value for value in attribute_values)
    assert not any(TOKEN in span.name for span in spans)
    assert any(REDACTED_PATH in value for value in attribute_values)
