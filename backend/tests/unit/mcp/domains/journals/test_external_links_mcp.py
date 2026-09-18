"""
Unit tests for journal MCP external links and integration source filtering.

Tests schema validation, converter behaviour, and filter parsing for
the external links extension to journal MCP tools (ITER5-006 Phase 1).
"""

from datetime import UTC, datetime, timedelta

import pytest
from core_shared.models.journals import EventDateRange, Journal
from pydantic import ValidationError

from app.core.integrations.external_link_helpers import ExternalLinkInfo
from app.mcp.domains.journals.converters import JournalConverter
from app.mcp.domains.journals.schemas import (
    ExternalLinkSchema,
    JournalResponse,
)
from app.mcp.domains.journals.tools.search import _parse_integration_source_filter


class TestExternalLinkSchema:
    """Tests for the ExternalLinkSchema Pydantic model."""

    def test_validates_with_all_fields(self) -> None:
        """Schema validates correctly with all fields populated."""
        link = ExternalLinkSchema(
            source="strava",
            url="https://www.strava.com/activities/12345",
            external_id="12345",
        )
        assert link.source == "strava"
        assert link.url == "https://www.strava.com/activities/12345"
        assert link.external_id == "12345"

    def test_accepts_url_none(self) -> None:
        """Schema accepts url=None for links where URL is not constructable."""
        link = ExternalLinkSchema(
            source="strava",
            url=None,
            external_id="athlete-456",
        )
        assert link.url is None
        assert link.source == "strava"
        assert link.external_id == "athlete-456"

    def test_rejects_missing_source(self) -> None:
        """Schema rejects missing source field."""
        with pytest.raises(ValidationError, match="source"):
            ExternalLinkSchema(
                url="https://example.com",
                external_id="123",
            )  # type: ignore[call-arg]

    def test_rejects_missing_external_id(self) -> None:
        """Schema rejects missing external_id field."""
        with pytest.raises(ValidationError, match="external_id"):
            ExternalLinkSchema(
                source="strava",
                url="https://example.com",
            )  # type: ignore[call-arg]


class TestJournalResponseExternalLinks:
    """Tests for external_links field on JournalResponse."""

    def test_external_links_defaults_to_empty_list(self) -> None:
        """JournalResponse.external_links defaults to empty list."""
        now = datetime.now(UTC)
        from app.mcp.domains.journals.schemas import EventDateRangeSchema

        response = JournalResponse(
            id=1,
            title="Test",
            content="Content",
            summary="Summary",
            event_date_range=EventDateRangeSchema(start=now, end=now),
            created_at=now,
            updated_at=now,
        )
        assert response.external_links == []

    def test_external_links_populated(self) -> None:
        """JournalResponse accepts populated external_links."""
        now = datetime.now(UTC)
        from app.mcp.domains.journals.schemas import EventDateRangeSchema

        link = ExternalLinkSchema(
            source="strava",
            url="https://www.strava.com/activities/12345",
            external_id="12345",
        )
        response = JournalResponse(
            id=1,
            title="Test",
            content="Content",
            summary="Summary",
            event_date_range=EventDateRangeSchema(start=now, end=now),
            external_links=[link],
            created_at=now,
            updated_at=now,
        )
        assert len(response.external_links) == 1
        assert response.external_links[0].source == "strava"


class TestJournalConverterExternalLinks:
    """Tests for JournalConverter.to_response external links handling."""

    def _make_journal(self) -> Journal:
        """Create a minimal Journal entity for testing."""
        now = datetime.now(UTC)
        return Journal(
            id=1,
            user_id="test-user",
            title="Test Journal",
            content="Test content",
            event_date_range=EventDateRange(start=now, end=now + timedelta(hours=1)),
            created_at=now,
            updated_at=now,
        )

    def test_includes_external_links_when_provided(self) -> None:
        """Converter includes external_links when ExternalLinkInfo list is provided."""
        journal = self._make_journal()
        external_links = [
            ExternalLinkInfo(
                source="strava",
                url="https://www.strava.com/activities/12345",
                external_id="12345",
                unique_key="12345",
            ),
            ExternalLinkInfo(
                source="google_calendar",
                url="https://calendar.google.com/calendar/event?eid=abc",
                external_id="event-abc",
                unique_key="event-abc",
            ),
            ExternalLinkInfo(
                source="snipeit",
                url="https://snipeit.example.com/hardware/42",
                external_id="42",
                unique_key="asset-42",
            ),
            ExternalLinkInfo(
                source="snipeit_maintenance",
                url="https://snipeit.example.com/hardware/42/maintenances/10",
                external_id="snipeit_maint:10",
                unique_key="snipeit_maint:10",
            ),
        ]

        response = JournalConverter.to_response(
            journal=journal,
            types=["fitness"],
            type_data={},
            contacts=[],
            tags=[],
            external_links=external_links,
        )

        assert len(response.external_links) == 4
        assert response.external_links[0].source == "strava"
        assert response.external_links[0].external_id == "12345"
        assert (
            response.external_links[0].url == "https://www.strava.com/activities/12345"
        )
        assert response.external_links[1].source == "google_calendar"
        assert response.external_links[1].external_id == "event-abc"

        assert response.external_links[2].source == "snipeit"
        assert response.external_links[2].external_id == "42"
        assert (
            response.external_links[2].url == "https://snipeit.example.com/hardware/42"
        )

        assert response.external_links[3].source == "snipeit_maintenance"
        assert response.external_links[3].external_id == "snipeit_maint:10"
        assert (
            response.external_links[3].url
            == "https://snipeit.example.com/hardware/42/maintenances/10"
        )

    def test_includes_immich_album_and_shared_links(self) -> None:
        """Converter surfaces Immich album and shared external links."""
        journal = self._make_journal()
        external_links = [
            ExternalLinkInfo(
                source="immich_album",
                url="https://immich.example.com/albums/album-uuid",
                external_id="album-uuid",
                unique_key="album-album-uuid",
            ),
            ExternalLinkInfo(
                source="immich_shared",
                url="https://immich.example.com/share/tok",
                external_id="album-uuid",
                unique_key="shared-album-uuid",
            ),
        ]

        response = JournalConverter.to_response(
            journal=journal,
            types=["photo_album"],
            type_data={},
            contacts=[],
            tags=[],
            external_links=external_links,
        )

        by_source = {link.source: link for link in response.external_links}
        assert set(by_source) == {"immich_album", "immich_shared"}
        assert by_source["immich_album"].url == (
            "https://immich.example.com/albums/album-uuid"
        )
        assert by_source["immich_shared"].url == "https://immich.example.com/share/tok"

    def test_returns_empty_external_links_when_not_provided(self) -> None:
        """Converter returns empty external_links when parameter is not provided."""
        journal = self._make_journal()

        response = JournalConverter.to_response(
            journal=journal,
            types=[],
            type_data={},
            contacts=[],
            tags=[],
        )

        assert response.external_links == []

    def test_returns_empty_external_links_when_none(self) -> None:
        """Converter returns empty external_links when None is passed explicitly."""
        journal = self._make_journal()

        response = JournalConverter.to_response(
            journal=journal,
            types=[],
            type_data={},
            contacts=[],
            tags=[],
            external_links=None,
        )

        assert response.external_links == []


class TestIntegrationSourceFilterParsing:
    """Tests for _parse_integration_source_filter validation."""

    def test_returns_none_for_none_input(self) -> None:
        """Returns None when no filter is provided."""
        assert _parse_integration_source_filter(None) is None

    def test_normalizes_valid_strava_source(self) -> None:
        """Normalizes 'strava' source correctly."""
        assert _parse_integration_source_filter("strava") == "strava"
        assert _parse_integration_source_filter("Strava") == "strava"
        assert _parse_integration_source_filter("  STRAVA  ") == "strava"

    def test_normalizes_valid_google_calendar_source(self) -> None:
        """Normalizes 'google_calendar' source correctly."""
        assert _parse_integration_source_filter("google_calendar") == "google_calendar"
        assert _parse_integration_source_filter("Google_Calendar") == "google_calendar"

    def test_normalizes_valid_snipeit_source(self) -> None:
        """Normalizes 'snipeit' source correctly."""
        assert _parse_integration_source_filter("snipeit") == "snipeit"
        assert _parse_integration_source_filter("SnipeIt") == "snipeit"

    def test_normalizes_valid_snipeit_maintenance_source(self) -> None:
        """Normalizes 'snipeit_maintenance' source correctly."""
        assert (
            _parse_integration_source_filter("snipeit_maintenance")
            == "snipeit_maintenance"
        )
        assert (
            _parse_integration_source_filter("Snipeit_Maintenance")
            == "snipeit_maintenance"
        )

    def test_normalizes_valid_immich_album_source(self) -> None:
        """Normalizes 'immich_album' source correctly."""
        assert _parse_integration_source_filter("immich_album") == "immich_album"
        assert _parse_integration_source_filter("Immich_Album") == "immich_album"
        assert _parse_integration_source_filter("  IMMICH_ALBUM  ") == "immich_album"

    def test_rejects_invalid_source(self) -> None:
        """Raises ValueError for unrecognized integration source."""
        with pytest.raises(ValueError, match="Invalid integration_source"):
            _parse_integration_source_filter("invalid_source")

    def test_invalid_source_message_lists_immich_album(self) -> None:
        """The error message advertises immich_album as an allowed source."""
        with pytest.raises(ValueError, match="immich_album"):
            _parse_integration_source_filter("not_a_source")

    def test_rejects_empty_string(self) -> None:
        """Raises ValueError for empty string integration source."""
        with pytest.raises(ValueError, match="Invalid integration_source"):
            _parse_integration_source_filter("")

    def test_rejects_whitespace_only(self) -> None:
        """Raises ValueError for whitespace-only integration source."""
        with pytest.raises(ValueError, match="Invalid integration_source"):
            _parse_integration_source_filter("   ")


class TestSearchJournalsToolRegistration:
    """Tests for search_journals tool schema including integration_source."""

    @pytest.fixture
    def mcp_server(self):
        """Create FastMCP server for testing."""
        from typing import Any

        from fastmcp import FastMCP

        from app.mcp.domains.journals.tools import register_journal_tools

        mcp: Any = FastMCP("TestServer")
        register_journal_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_search_journals_has_integration_source_parameter(
        self, mcp_server
    ) -> None:
        """search_journals tool schema includes integration_source parameter."""
        from fastmcp import Client

        async with Client(mcp_server) as client:
            tools = await client.list_tools()
            search_tool = next((t for t in tools if t.name == "search_journals"), None)
            assert search_tool is not None, "search_journals tool not found"

            properties = search_tool.input_schema.get("properties", {})
            assert "integration_source" in properties, (
                "integration_source parameter not found in search_journals schema"
            )
