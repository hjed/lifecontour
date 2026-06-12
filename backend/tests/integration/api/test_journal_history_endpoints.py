"""Integration tests for the journal history API endpoint (ITER12-002 Phase 2).

Mirrors ``test_history_endpoints.py`` (contacts): empty state, populated entries,
pagination, 404, JSON:API shape, and most-recent-first ordering across mixed
provenance sources. History rows are seeded directly through the shared
``SqlFieldHistoryRepository`` (the same rows the projection consumer writes), so
these tests isolate the read endpoint from the async projection.
"""

from datetime import UTC, datetime, timedelta

import pytest
from core_shared.models.history import Provenance
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.models import FieldHistoryEntry


async def _seed(
    connection: AsyncConnection,
    journal_id: int,
    field_name: str,
    *,
    old_value: str | None,
    new_value: str | None,
    changed_by: str,
    source: Provenance,
    created_at: datetime,
    event_id: str,
) -> None:
    repo = SqlFieldHistoryRepository(connection)
    await repo.record_change(
        FieldHistoryEntry(
            entity_type="journal",
            entity_id=journal_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
            source=source,
            event_id=event_id,
            created_at=created_at,
        )
    )


class TestJournalHistoryEndpoint:
    @pytest.mark.asyncio
    async def test_get_journal_history_empty(
        self, authenticated_client, sample_journal_id: int
    ) -> None:
        """A journal with no recorded changes returns an empty data list."""
        response = await authenticated_client.get(
            f"/api/journals/{sample_journal_id}/history"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"] == []

    @pytest.mark.asyncio
    async def test_get_journal_history_after_change(
        self,
        authenticated_client,
        sample_journal_id: int,
        async_connection: AsyncConnection,
    ) -> None:
        """A recorded change is returned with provenance and old/new values."""
        await _seed(
            async_connection,
            sample_journal_id,
            "title",
            old_value="Old",
            new_value="New",
            changed_by="ui",
            source=Provenance.UI,
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            event_id="evt-title",
        )

        response = await authenticated_client.get(
            f"/api/journals/{sample_journal_id}/history"
        )

        assert response.status_code == 200
        entries = response.json()["data"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["type"] == "journal_history"
        attrs = entry["attributes"]
        assert attrs["entity_type"] == "journal"
        assert attrs["entity_id"] == sample_journal_id
        assert attrs["field_name"] == "title"
        assert attrs["old_value"] == "Old"
        assert attrs["new_value"] == "New"
        assert attrs["source"] == "ui"
        assert attrs["changed_by"] == "ui"
        assert attrs["created_at"] is not None

    @pytest.mark.asyncio
    async def test_get_journal_history_pagination(
        self,
        authenticated_client,
        sample_journal_id: int,
        async_connection: AsyncConnection,
    ) -> None:
        """Pagination limits page size and reports totals in meta."""
        base = datetime(2024, 1, 1, tzinfo=UTC)
        for i in range(5):
            await _seed(
                async_connection,
                sample_journal_id,
                f"field_{i}",
                old_value=None,
                new_value=str(i),
                changed_by="ui",
                source=Provenance.UI,
                created_at=base + timedelta(minutes=i),
                event_id=f"evt-{i}",
            )

        response = await authenticated_client.get(
            f"/api/journals/{sample_journal_id}/history?page=1&limit=2"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 2
        assert data["meta"]["current_page"] == 1
        assert data["meta"]["per_page"] == 2
        assert data["meta"]["total_count"] == 5

        page3 = await authenticated_client.get(
            f"/api/journals/{sample_journal_id}/history?page=3&limit=2"
        )
        assert len(page3.json()["data"]) == 1

    @pytest.mark.asyncio
    async def test_get_journal_history_not_found(self, authenticated_client) -> None:
        """A missing journal returns 404 with a JSON:API errors object."""
        response = await authenticated_client.get("/api/journals/999999/history")

        assert response.status_code == 404
        assert "errors" in response.json()

    @pytest.mark.asyncio
    async def test_get_journal_history_json_api_structure(
        self,
        authenticated_client,
        sample_journal_id: int,
        async_connection: AsyncConnection,
    ) -> None:
        """Each entry follows the JSON:API resource shape."""
        await _seed(
            async_connection,
            sample_journal_id,
            "content",
            old_value="a",
            new_value="b",
            changed_by="mcp",
            source=Provenance.MCP,
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            event_id="evt-content",
        )

        data = (
            await authenticated_client.get(f"/api/journals/{sample_journal_id}/history")
        ).json()

        entry = data["data"][0]
        assert {"type", "id", "attributes"}.issubset(entry.keys())
        attrs = entry["attributes"]
        for key in (
            "entity_type",
            "entity_id",
            "field_name",
            "old_value",
            "new_value",
            "source",
            "created_at",
        ):
            assert key in attrs

    @pytest.mark.asyncio
    async def test_get_journal_history_ordered_most_recent_first(
        self,
        authenticated_client,
        sample_journal_id: int,
        async_connection: AsyncConnection,
    ) -> None:
        """Mixed-source entries are returned newest-first with each provenance."""
        base = datetime(2024, 1, 1, tzinfo=UTC)
        # Seed oldest -> newest so ordering must be applied by the query, not insert.
        await _seed(
            async_connection,
            sample_journal_id,
            "title",
            old_value="t0",
            new_value="t1",
            changed_by="ui",
            source=Provenance.UI,
            created_at=base,
            event_id="evt-ui",
        )
        await _seed(
            async_connection,
            sample_journal_id,
            "mood_value",
            old_value="3",
            new_value="7",
            changed_by="mcp",
            source=Provenance.MCP,
            created_at=base + timedelta(minutes=1),
            event_id="evt-mcp",
        )
        await _seed(
            async_connection,
            sample_journal_id,
            "distance",
            old_value=None,
            new_value="5000",
            changed_by="system",
            source=Provenance.STRAVA,
            created_at=base + timedelta(minutes=2),
            event_id="evt-strava",
        )

        entries = (
            await authenticated_client.get(f"/api/journals/{sample_journal_id}/history")
        ).json()["data"]

        sources = [e["attributes"]["source"] for e in entries]
        assert sources == ["strava", "mcp", "ui"]
