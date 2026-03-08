"""Helpers for resetting SSE test state between lifespan-managed tests."""

from importlib import import_module


def reset_sse_starlette_appstatus_event() -> None:
    """Reset sse-starlette's global shutdown event when available."""
    try:
        sse_module = import_module("sse_starlette.sse")
    except ModuleNotFoundError:
        return

    app_status = getattr(sse_module, "AppStatus", None)
    if app_status is None:
        return

    app_status.should_exit_event = None
