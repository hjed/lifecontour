"""Regression tests for the Gemini + read-only-MCP tool-calling integration.

The AI summary services (daily summary and contact summary) pass a *live*
``fastmcp`` MCP ``ClientSession`` to ``google-genai`` as a tool — the pattern
recommended by both libraries' docs:

    config=types.GenerateContentConfig(tools=[mcp_client.session])

google-genai 2.8.0 introduced a regression where ``generate_content`` does
``config.model_copy(deep=True)`` at the top of the call (models.py:8543). The
live session holds ``_asyncio.Future`` objects, so the deep copy raises
``cannot pickle '_asyncio.Future' object`` on the very first request — which is
what broke daily-summary sync.

These tests exercise the exact integration path both services rely on, mocking
only the network layer (``_generate_content``). They fail on google-genai 2.8.0
and pass on 2.7.0, guarding the ``google-genai<2.8.0`` pin in pyproject.toml.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from fastmcp import Client
from google import genai
from google.genai import types

from app.core.contacts.services.summary_generation_service import SummaryGenerator
from app.core.journal.services.daily_summary_service import DailySummaryService
from app.mcp.shared.read_only_tools import create_read_only_mcp_server


def _text_response(text: str) -> types.GenerateContentResponse:
    """Build a minimal model response containing plain text (no tool calls)."""
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=text)])
            )
        ]
    )


async def test_generate_content_with_live_mcp_session_does_not_pickle() -> None:
    """The documented ``tools=[session]`` pattern must not raise a pickle error.

    Reproduces the daily-summary failure at the library boundary: a real
    read-only MCP server + live ``fastmcp`` session passed to
    ``generate_content``. Only the network call is mocked, so the buggy
    ``model_copy(deep=True)`` path in google-genai still executes.
    """
    read_only_mcp = await create_read_only_mcp_server("Daily Summary Generation Tools")

    client = genai.Client(api_key="test-key")
    # Mock the network layer; the real ``generate_content`` orchestrator (which
    # deep-copies the config on 2.8.0) still runs.
    client.aio.models._generate_content = AsyncMock(  # type: ignore[method-assign]
        return_value=_text_response("a summary of the day")
    )

    async with Client(read_only_mcp) as mcp_client:
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents="Summarise the day",
            config=types.GenerateContentConfig(
                tools=[mcp_client.session],
                temperature=0.3,
            ),
        )

    assert response.text == "a summary of the day"


async def test_read_only_mcp_session_config_is_passed_through() -> None:
    """The live session is accepted as a tool and converted by the SDK.

    Confirms the read-only server exposes tools and that a session-backed
    config reaches the (mocked) transport without error.
    """
    read_only_mcp = await create_read_only_mcp_server("Summary Generation Tools")

    client = genai.Client(api_key="test-key")
    transport = AsyncMock(return_value=_text_response("ok"))
    client.aio.models._generate_content = transport  # type: ignore[method-assign]

    async with Client(read_only_mcp) as mcp_client:
        tools = await mcp_client.list_tools()
        assert tools, "read-only server should expose at least one tool"

        result = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents="hi",
            config=types.GenerateContentConfig(
                tools=[mcp_client.session],
                temperature=0.3,
            ),
        )

    assert result.text == "ok"
    transport.assert_awaited()


@contextmanager
def _mock_gemini_transport(text: str) -> Iterator[None]:
    """Patch ``genai.Client`` so its network layer returns ``text``.

    The real ``generate_content`` orchestrator still runs (including the 2.8.0
    deep-copy path), so this exercises the genuine service code path while
    avoiding any network call.
    """
    original_client_cls = genai.Client

    def factory(*args: object, **kwargs: object) -> genai.Client:
        client = original_client_cls(*args, **kwargs)  # type: ignore[arg-type]
        client.aio.models._generate_content = AsyncMock(  # type: ignore[method-assign]
            return_value=_text_response(text)
        )
        return client

    with patch("google.genai.Client", side_effect=factory):
        yield


async def test_daily_summary_service_call_gemini_returns_text() -> None:
    """``DailySummaryService._call_gemini`` completes with live MCP tools.

    Exercises the exact method that failed in production (it passes
    ``mcp_client.session`` to Gemini), with only the network mocked.
    """
    service = DailySummaryService(
        input_assembler=AsyncMock(),
        eligibility_checker=MagicMock(),
        prompt_builder=MagicMock(),
        summary_repo=AsyncMock(),
        gemini_api_key="test-key",
        gemini_model="gemini-2.5-flash",
    )

    with _mock_gemini_transport('{"summary_text": "a good day"}'):
        result = await service._call_gemini("Summarise the day")

    assert result == '{"summary_text": "a good day"}'


async def test_contact_summary_generator_call_gemini_returns_text() -> None:
    """``SummaryGenerator._call_gemini`` completes with live MCP tools.

    The contact-summary path uses the same ``tools=[mcp_client.session]``
    pattern as the daily summary and must not hit the pickle regression.
    """
    generator = SummaryGenerator(
        input_assembler=MagicMock(),
        activity_checker=MagicMock(),
        prompt_builder=MagicMock(),
        summary_repo=AsyncMock(),
        gemini_api_key="test-key",
        gemini_model="gemini-2.5-flash",
    )

    with _mock_gemini_transport('{"summary_text": "knows Alice"}'):
        result = await generator._call_gemini("Summarise the contact")

    assert result == '{"summary_text": "knows Alice"}'
