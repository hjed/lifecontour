"""The MCP journal tools report the same enrichment REST does.

Every tool that answers with a journal reads it through
``JournalEnrichmentService``, so a write tool's answer carries the same series
and calendars ``get_journal`` does, an abseiling trip carries its pitches, and
a contact's name follows the one null-safe rule.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from core_shared.models.journals import (
    AbseilingData,
    AbseilPitch,
    JournalContactRelationship,
    JournalContactRelationshipType,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.abseil_pitch_repository import (
    SqlAbseilPitchRepository,
)
from app.core.journal.adapters.sql.abseiling_data_repository import (
    SqlAbseilingDataRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_series_repository import (
    SqlJournalSeriesRepository,
)
from app.core.journal.models.journal_series import JournalSeries
from tests.integration.contact_seeding import seed_contact
from tests.integration.linked_calendar_seeding import USER_ID, seed_shared_event
from tests.integration.mcp.http_helpers import call_mcp_tool

pytestmark = pytest.mark.integration


async def _create_journal(conn: AsyncConnection, title: str = "A note") -> int:
    start = datetime.now(UTC) - timedelta(days=1)
    result = await conn.execute(
        text("""
            INSERT INTO journals (user_id, title, content,
                                  event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, '', :start, :end)
            RETURNING id
        """),
        {
            "user_id": USER_ID,
            "title": title,
            "start": start,
            "end": start + timedelta(hours=1),
        },
    )
    return int(result.scalar_one())


async def _add_to_series(conn: AsyncConnection, journal_id: int, name: str) -> None:
    repo = SqlJournalSeriesRepository(conn)
    series = await repo.save(JournalSeries(name=name, user_id=USER_ID))
    assert series.id is not None
    await repo.add_member(series.id, journal_id)


class TestGetJournal:
    async def test_abseiling_type_data_carries_its_pitches(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
    ) -> None:
        journal_id = await _create_journal(clean_database, "Pitches")
        await SqlAbseilingDataRepository(clean_database).save(
            AbseilingData(journal_id=journal_id, number_of_abseils=2)
        )
        pitch_repo = SqlAbseilPitchRepository(clean_database)
        await pitch_repo.save(
            AbseilPitch(
                journal_id=journal_id,
                pitch_number=1,
                height=30,
                anchor_type="chains",
                pitch_type="abseil",
            )
        )
        await pitch_repo.save(AbseilPitch(journal_id=journal_id, pitch_number=2))

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client, "get_journal", {"journal_id": journal_id}
            )

        pitches = payload["type_data"]["abseiling_trip"]["pitches"]
        assert [p["pitch_number"] for p in pitches] == [1, 2]
        assert pitches[0]["height"] == 30
        assert pitches[0]["anchor_type"] == "chains"
        assert pitches[0]["pitch_type"] == "abseil"

    async def test_contact_without_a_last_name_reads_as_the_first_name(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
    ) -> None:
        journal_id = await _create_journal(clean_database)
        contact_id = await seed_contact(clean_database, first_name="Jane")
        await SqlJournalContactRelationshipRepository(clean_database).create(
            JournalContactRelationship(
                journal_id=journal_id,
                contact_id=contact_id,
                relationship_type=JournalContactRelationshipType.MENTION,
            )
        )

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client, "get_journal", {"journal_id": journal_id}
            )

        assert [c["name"] for c in payload["contacts"]] == ["Jane"]


class TestWriteToolsReportTheFullJournal:
    async def test_update_reports_series_and_calendars(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
    ) -> None:
        journal_id, work, personal = await seed_shared_event(clean_database)
        await _add_to_series(clean_database, journal_id, "Weekly physio")

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "update_journal_entry",
                {"journal_id": journal_id, "request": {"content": "Went well"}},
            )

        assert [s["name"] for s in payload["series"]] == ["Weekly physio"]
        assert [c["id"] for c in payload["calendars"]] == [work, personal]

    async def test_merge_reports_the_survivors_series(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
    ) -> None:
        target_id = await _create_journal(clean_database, "Target")
        source_id = await _create_journal(clean_database, "Source")
        await _add_to_series(clean_database, target_id, "Training block")

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "merge_journals",
                {
                    "target_journal_id": target_id,
                    "merge_data": json.dumps({"source_journal_id": source_id}),
                },
            )

        assert payload["id"] == target_id
        assert [s["name"] for s in payload["series"]] == ["Training block"]


class TestMergeCandidates:
    async def test_an_untyped_candidate_is_a_note(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
    ) -> None:
        target_id = await _create_journal(clean_database, "Target")
        candidate_id = await _create_journal(clean_database, "Candidate")

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client, "get_merge_candidates", {"journal_id": target_id}
            )

        by_id = {c["id"]: c for c in payload["candidates"]}
        assert by_id[candidate_id]["types"] == ["note"]
