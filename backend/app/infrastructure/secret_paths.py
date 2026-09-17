"""
Keep secrets carried in URL paths out of logs and traces.

Snipe-IT webhooks have no signature, so the webhook URL's last path segment is
the credential (see ``snipeit_webhook_controller``). Anything that records a
request path - error-handler logs, OpenTelemetry request spans - would otherwise
store a working credential. Redaction replaces the segment with its route
parameter name, so the logged path still says which endpoint was hit.
"""

import re
from typing import Any

from opentelemetry.trace import Span
from structlog.types import EventDict

_SECRET_PATH_SEGMENT = re.compile(
    r"(?P<prefix>/api/integrations/snipeit/webhook/)[^/?#\s\"']+"
)
_REDACTED_SEGMENT = r"\g<prefix>{webhook_token}"

# Request span attributes that hold the path, under the old and new HTTP
# semantic conventions. Span names use the route template, so they are safe.
_URL_SPAN_ATTRIBUTES = ("http.target", "url.path", "http.url", "url.full")


def redact_secret_paths(text: str) -> str:
    """Replace every secret path segment in ``text`` with its parameter name."""
    return _SECRET_PATH_SEGMENT.sub(_REDACTED_SEGMENT, text)


def redact_secret_paths_processor(
    _logger: Any, _method_name: str, event_dict: EventDict
) -> EventDict:
    """Structlog processor redacting secret path segments from string values."""
    return {
        key: redact_secret_paths(value) if isinstance(value, str) else value
        for key, value in event_dict.items()
    }


def redact_secret_path_span_attributes(span: Span, scope: dict[str, Any]) -> None:
    """
    OpenTelemetry ASGI ``server_request_hook`` redacting secret path segments.

    The instrumentation sets the URL attributes before calling the hook, so the
    hook overwrites the ones that were recorded.
    """
    if not span.is_recording():
        return
    attributes = getattr(span, "attributes", None) or {}
    for key in _URL_SPAN_ATTRIBUTES:
        value = attributes.get(key)
        if isinstance(value, str):
            span.set_attribute(key, redact_secret_paths(value))
