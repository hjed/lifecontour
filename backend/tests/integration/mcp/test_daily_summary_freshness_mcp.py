"""MCP ``get_daily_summary`` inherits the freshness rule from the service.

The specification says the staleness refresh is a property of the summary, not
of the surface asking for it, so the tool has no logic of its own to test —
what is tested is that it *has* none: the request goes through the mounted MCP
app, the real container, the real ``DailySummaryService`` and the real
repository, with only the Gemini call replaced by a counting stub. A stale
today-summary comes back regenerated and a fresh one comes back cached, exactly
as the REST endpoint would answer.

The clock the DI-built checkers read is pinned so "today" is a fixed date and
the seeded rows are stale or fresh by construction rather than by luck.
"""

import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals.daily_summary import JournalDailySummary
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.daily_summary_repository import (
    SqlJournalDailySummaryRepository,
)
from app.core.journal.services import (
    daily_summary_eligibility,
    daily_summary_freshness,
    daily_summary_service,
)
from app.core.journal.services.daily_summary_service import DailySummaryService
from app.infrastructure.di.journal import DAILY_SUMMARY_STUB_TEXT
from tests.integration.mcp.http_helpers import (
    call_mcp_tool,
)

USER_ID = "test-user-123"  # the id ``test_user`` authenticates as
# 07:00 UTC on 3 September; the test user has no saved timezone, so UTC.
NOW = datetime(2026, 9, 3, 7, 0, tzinfo=UTC)
TODAY = date(2026, 9, 3)
LAST_NIGHT = datetime(2026, 9, 2, 22, 0, tzinfo=UTC)
EARLY_TODAY = datetime(2026, 9, 3, 0, 30, tzinfo=UTC)
OLD_TEXT = "Written last night."
NEW_TEXT = "Written this morning."


@pytest.fixture
def pinned_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fix the instant the DI-built pipeline reads as *now*.

    The service reads the clock once and imposes that instant on the checkers,
    so pinning it there is what decides the day; the checkers' own defaults are
    pinned too, for any path that calls them without one.
    """
    monkeypatch.setattr(daily_summary_service, "_utc_now", lambda: NOW)
    monkeypatch.setattr(daily_summary_freshness, "_utc_now", lambda: NOW)
    monkeypatch.setattr(daily_summary_eligibility, "_utc_now", lambda: NOW)


@pytest.fixture
def gemini_configured(test_settings) -> None:
    """Without a key the service answers ``None`` before it reads the cache."""
    test_settings.gemini_api_key = "test-key"


@pytest.fixture
async def gemini_stub() -> AsyncIterator[AsyncMock]:
    stub = AsyncMock(return_value=json.dumps({"summary_text": NEW_TEXT}))
    with patch.object(DailySummaryService, "_call_gemini", stub):
        yield stub


async def seed_todays_summary(
    connection: AsyncConnection, generated_at: datetime
) -> None:
    await SqlJournalDailySummaryRepository(connection).upsert(
        JournalDailySummary(
            user_id=USER_ID,
            summary_date=TODAY,
            summary_text=OLD_TEXT,
            journal_count=2,
            status=SummaryStatus.GENERATED,
            generated_at=generated_at,
        )
    )


async def call_get_daily_summary(client: Any) -> dict[str, Any]:
    return await call_mcp_tool(
        client, "get_daily_summary", {"summary_date": TODAY.isoformat()}
    )


@pytest.mark.integration
@pytest.mark.usefixtures("pinned_clock", "gemini_configured")
class TestGetDailySummaryInheritsFreshness:
    @pytest.mark.asyncio
    async def test_a_stale_today_summary_is_regenerated(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        gemini_stub: AsyncMock,
    ) -> None:
        await seed_todays_summary(clean_database, LAST_NIGHT)

        async with authenticated_lifespan_client() as client:
            payload = await call_get_daily_summary(client)

        assert "error" not in payload
        assert payload["status"] == "generated"
        assert payload["summary_text"] == NEW_TEXT
        gemini_stub.assert_awaited_once()
        persisted = await SqlJournalDailySummaryRepository(
            clean_database
        ).find_by_user_and_date(USER_ID, TODAY)
        assert persisted is not None
        assert persisted.summary_text == NEW_TEXT

    @pytest.mark.asyncio
    async def test_a_fresh_today_summary_is_served_from_cache(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        gemini_stub: AsyncMock,
    ) -> None:
        await seed_todays_summary(clean_database, EARLY_TODAY)

        async with authenticated_lifespan_client() as client:
            payload = await call_get_daily_summary(client)

        assert "error" not in payload
        assert payload["status"] == "generated"
        assert payload["summary_text"] == OLD_TEXT
        gemini_stub.assert_not_awaited()


@pytest.fixture
def daily_summary_stub(test_settings) -> None:
    """The e2e stack's model: no key, only the settings-driven stub.

    Nothing is patched here, so these tests also prove the flag reaches the
    service through the container MCP resolves it from.
    """
    test_settings.gemini_api_key = ""
    test_settings.enable_test_daily_summary_stub = True


@pytest.mark.integration
@pytest.mark.usefixtures("pinned_clock", "daily_summary_stub")
class TestGetDailySummaryInheritsEligibilityAndInvalidation:
    """Today is always eligible, and an invalidated today regenerates on read."""

    @pytest.mark.asyncio
    async def test_a_quiet_today_is_generated_not_disabled(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        async with authenticated_lifespan_client() as client:
            payload = await call_get_daily_summary(client)

        assert "error" not in payload
        assert payload["status"] == "generated"
        assert payload["summary_text"] == DAILY_SUMMARY_STUB_TEXT
        assert payload["journal_count"] == 0

    @pytest.mark.asyncio
    async def test_an_invalidated_today_is_regenerated_on_read(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        await seed_todays_summary(clean_database, EARLY_TODAY)
        await SqlJournalDailySummaryRepository(clean_database).invalidate_for_date(
            USER_ID, TODAY
        )

        async with authenticated_lifespan_client() as client:
            payload = await call_get_daily_summary(client)

        assert "error" not in payload
        assert payload["status"] == "generated"
        assert payload["summary_text"] == DAILY_SUMMARY_STUB_TEXT
