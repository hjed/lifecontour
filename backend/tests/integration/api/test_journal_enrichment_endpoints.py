"""The REST journal reads report the enrichment MCP does.

``GET /api/journals/{id}`` and ``GET /api/journals`` read a journal's types,
type data, contacts, tags, series and calendars through
``JournalEnrichmentService``; child types come from its batch ``types_for``.
"""

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
from tests.integration.contact_seeding import TEST_USER_ID, seed_contact

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_database")]


async def _create_journal(
    conn: AsyncConnection, title: str, *, parent_id: int | None = None
) -> int:
    start = datetime.now(UTC) - timedelta(days=1)
    result = await conn.execute(
        text("""
            INSERT INTO journals (user_id, title, content, parent_id,
                                  event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, '', :parent_id, :start, :end)
            RETURNING id
        """),
        {
            "user_id": TEST_USER_ID,
            "title": title,
            "parent_id": parent_id,
            "start": start,
            "end": start + timedelta(hours=1),
        },
    )
    return int(result.scalar_one())


async def _add_to_series(conn: AsyncConnection, journal_id: int, name: str) -> None:
    repo = SqlJournalSeriesRepository(conn)
    series = await repo.save(JournalSeries(name=name, user_id=TEST_USER_ID))
    assert series.id is not None
    await repo.add_member(series.id, journal_id)


class TestJournalDetail:
    async def test_an_untyped_child_is_a_note(
        self, integration_api_client: Any, async_connection: AsyncConnection
    ) -> None:
        parent_id = await _create_journal(async_connection, "Trip")
        child_id = await _create_journal(
            async_connection, "Day one", parent_id=parent_id
        )

        response = await integration_api_client.get(f"/api/journals/{parent_id}")

        assert response.status_code == 200
        children = response.json()["data"]["attributes"]["children"]
        assert [(c["id"], c["types"]) for c in children] == [(str(child_id), ["note"])]

    async def test_abseiling_type_data_carries_its_pitches(
        self, integration_api_client: Any, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _create_journal(async_connection, "Abseil")
        await SqlAbseilingDataRepository(async_connection).save(
            AbseilingData(journal_id=journal_id, number_of_abseils=1)
        )
        await SqlAbseilPitchRepository(async_connection).save(
            AbseilPitch(journal_id=journal_id, pitch_number=1, height=25)
        )

        response = await integration_api_client.get(f"/api/journals/{journal_id}")

        abseiling = response.json()["data"]["attributes"]["type_data"]["abseiling_trip"]
        assert abseiling["number_of_abseils"] == 1
        assert [(p["pitch_number"], p["height"]) for p in abseiling["pitches"]] == [
            (1, 25)
        ]

    async def test_contacts_carry_names_and_series_are_listed(
        self, integration_api_client: Any, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _create_journal(async_connection, "Coffee")
        contact_id = await seed_contact(async_connection, first_name="Jane")
        await SqlJournalContactRelationshipRepository(async_connection).create(
            JournalContactRelationship(
                journal_id=journal_id,
                contact_id=contact_id,
                relationship_type=JournalContactRelationshipType.MENTION,
            )
        )
        await _add_to_series(async_connection, journal_id, "Catch-ups")

        response = await integration_api_client.get(f"/api/journals/{journal_id}")

        attributes = response.json()["data"]["attributes"]
        assert [
            (c["id"], c["name"], c["last_name"]) for c in attributes["contacts"]
        ] == [(str(contact_id), "Jane", None)]
        assert [s["name"] for s in attributes["series"]] == ["Catch-ups"]


class TestJournalList:
    async def test_list_rows_carry_their_series(
        self, integration_api_client: Any, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _create_journal(async_connection, "Weekly run")
        await _add_to_series(async_connection, journal_id, "Running club")

        response = await integration_api_client.get("/api/journals")

        assert response.status_code == 200
        rows = {row["id"]: row for row in response.json()["data"]}
        assert [s["name"] for s in rows[str(journal_id)]["attributes"]["series"]] == [
            "Running club"
        ]


class TestJournalWrites:
    async def test_patch_answers_with_series_and_typed_children(
        self, integration_api_client: Any, async_connection: AsyncConnection
    ) -> None:
        parent_id = await _create_journal(async_connection, "Trip")
        child_id = await _create_journal(
            async_connection, "Day one", parent_id=parent_id
        )
        await _add_to_series(async_connection, parent_id, "Trips")

        response = await integration_api_client.patch(
            f"/api/journals/{parent_id}",
            json={
                "data": {
                    "type": "journals",
                    "id": str(parent_id),
                    "attributes": {"content": "Updated"},
                }
            },
        )

        assert response.status_code == 200
        attributes = response.json()["data"]["attributes"]
        assert [s["name"] for s in attributes["series"]] == ["Trips"]
        assert [(c["id"], c["types"]) for c in attributes["children"]] == [
            (str(child_id), ["note"])
        ]

    async def test_adding_a_contact_answers_with_its_name(
        self, integration_api_client: Any, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _create_journal(async_connection, "Lunch")
        contact_id = await seed_contact(
            async_connection, first_name="Sam", last_name="Lee"
        )

        response = await integration_api_client.post(
            f"/api/journals/{journal_id}/relationships/contacts",
            json={
                "data": {
                    "type": "journal-contact-relationships",
                    "attributes": {
                        "contact_id": str(contact_id),
                        "relationship_type": "MENTION",
                    },
                }
            },
        )

        assert response.status_code == 200, response.text
        contacts = response.json()["data"]["attributes"]["contacts"]
        assert [(c["id"], c["name"]) for c in contacts] == [
            (str(contact_id), "Sam Lee")
        ]
