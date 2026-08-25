"""An event in two calendars reads as being in two calendars.

De-duplication gives one journal several `journal_external_event_links`,
one per calendar holding the event. `journal_calendar_info` still holds a
single calendar — the one the journal is displayed in — so a read that only
ever looked there would show a shared event sitting in one calendar and
silently drop the other.

These tests seed the links directly rather than driving the sync, because
their subject is the read model: given a journal linked to two calendars,
what does the API say? How it came to be linked is the sync's tests.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.linked_calendar_seeding import (
    PERSONAL_COLOUR,
    USER_ID,
    WORK_COLOUR,
    create_calendar,
    create_event_journal,
    link_calendar,
    seed_shared_event,
)

pytestmark = pytest.mark.integration


def _attributes(payload: dict[str, Any]) -> dict[str, Any]:
    attributes: dict[str, Any] = payload["data"]["attributes"]
    return attributes


class TestReadingASharedEvent:
    async def test_every_linked_calendar_is_reported(
        self,
        authenticated_client: Any,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        journal_id, work, personal = await seed_shared_event(async_connection)

        response = await authenticated_client.get(f"/api/journals/{journal_id}")

        assert response.status_code == 200
        calendars = _attributes(response.json())["calendars"]
        assert [calendar["id"] for calendar in calendars] == [work, personal]

    async def test_the_display_calendar_comes_first(
        self,
        authenticated_client: Any,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """The order carries meaning, so a client need not re-derive it.

        The first entry is the calendar the journal belongs to; the rest are
        calendars that also hold the event. A client rendering the list in
        order gets the primary badge first without comparing ids.
        """
        journal_id, work, _personal = await seed_shared_event(async_connection)

        response = await authenticated_client.get(f"/api/journals/{journal_id}")

        attributes = _attributes(response.json())
        assert attributes["calendars"][0]["id"] == work
        assert attributes["calendar"]["id"] == work

    async def test_each_entry_carries_what_a_badge_needs(
        self,
        authenticated_client: Any,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Name and colour, so no follow-up request is needed to render one."""
        journal_id, _work, _personal = await seed_shared_event(async_connection)

        response = await authenticated_client.get(f"/api/journals/{journal_id}")

        calendars = _attributes(response.json())["calendars"]
        assert [c["name"] for c in calendars] == ["Work", "Personal"]
        assert [c["color"] for c in calendars] == [WORK_COLOUR, PERSONAL_COLOUR]

    async def test_the_existing_calendar_field_is_unchanged(
        self,
        authenticated_client: Any,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Existing clients keep reading the single calendar they always did."""
        journal_id, work, _personal = await seed_shared_event(async_connection)

        response = await authenticated_client.get(f"/api/journals/{journal_id}")

        calendar = _attributes(response.json())["calendar"]
        assert calendar["id"] == work
        assert calendar["name"] == "Work"


class TestReadingAnOrdinaryEvent:
    async def test_a_single_calendar_event_reports_one_calendar(
        self,
        authenticated_client: Any,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        work = await create_calendar(async_connection, "Work")
        journal_id = await create_event_journal(
            async_connection, title="Standup", display_calendar_id=work
        )
        await link_calendar(
            async_connection,
            journal_id=journal_id,
            calendar_id=work,
            external_event_id="only-copy",
        )

        response = await authenticated_client.get(f"/api/journals/{journal_id}")

        calendars = _attributes(response.json())["calendars"]
        assert [c["id"] for c in calendars] == [work]

    async def test_an_event_with_no_links_still_reports_its_calendar(
        self,
        authenticated_client: Any,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """A hand-made event has a calendar but nothing synced against it."""
        work = await create_calendar(async_connection, "Work")
        journal_id = await create_event_journal(
            async_connection, title="Dentist", display_calendar_id=work
        )

        response = await authenticated_client.get(f"/api/journals/{journal_id}")

        calendars = _attributes(response.json())["calendars"]
        assert [c["id"] for c in calendars] == [work]

    async def test_a_non_event_journal_reports_no_calendars(
        self,
        authenticated_client: Any,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        result = await async_connection.execute(
            text("""
                INSERT INTO journals
                    (user_id, title, content,
                     event_date_range_start, event_date_range_end)
                VALUES (:user_id, 'Just a note', '', :now, :now)
                RETURNING id
            """),
            {"user_id": USER_ID, "now": datetime.now(UTC)},
        )
        journal_id = int(result.scalar_one())

        response = await authenticated_client.get(f"/api/journals/{journal_id}")

        attributes = _attributes(response.json())
        assert attributes["calendars"] == []
        assert attributes["calendar"] is None


class TestTheJournalList:
    async def test_the_list_reports_linked_calendars_too(
        self,
        authenticated_client: Any,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """The list is where a shared event is most likely to be seen."""
        journal_id, work, personal = await seed_shared_event(async_connection)

        response = await authenticated_client.get("/api/journals?limit=50")

        assert response.status_code == 200
        entry = next(
            item for item in response.json()["data"] if int(item["id"]) == journal_id
        )
        assert [c["id"] for c in entry["attributes"]["calendars"]] == [
            work,
            personal,
        ]


class TestFilteringByCalendar:
    async def test_the_second_calendar_finds_the_shared_event(
        self,
        authenticated_client: Any,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Filtering by the personal calendar must show the shared event.

        Before de-duplication the personal calendar had a journal of its
        own, so filtering found it. Now that the two share one journal —
        displayed in the work calendar — a filter that only consulted
        `journal_calendar_info` would make the event vanish from the
        personal calendar entirely.
        """
        journal_id, _work, personal = await seed_shared_event(async_connection)

        response = await authenticated_client.get(
            f"/api/journals?calendar_id={personal}&limit=50"
        )

        assert response.status_code == 200
        assert [int(item["id"]) for item in response.json()["data"]] == [journal_id]

    async def test_the_display_calendar_still_finds_it(
        self,
        authenticated_client: Any,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        journal_id, work, _personal = await seed_shared_event(async_connection)

        response = await authenticated_client.get(
            f"/api/journals?calendar_id={work}&limit=50"
        )

        assert [int(item["id"]) for item in response.json()["data"]] == [journal_id]

    async def test_an_unrelated_calendar_finds_nothing(
        self,
        authenticated_client: Any,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Widening the filter must not turn it into a match-anything."""
        await seed_shared_event(async_connection)
        other = await create_calendar(async_connection, "Someone else's")

        response = await authenticated_client.get(
            f"/api/journals?calendar_id={other}&limit=50"
        )

        assert response.json()["data"] == []

    async def test_the_shared_event_is_returned_once(
        self,
        authenticated_client: Any,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Joining onto the links must not multiply rows.

        A journal with two links joined naively returns twice — once per
        link — which would show the user the same event twice in a list.
        """
        journal_id, work, _personal = await seed_shared_event(async_connection)

        response = await authenticated_client.get(
            f"/api/journals?calendar_id={work}&limit=50"
        )

        ids = [int(item["id"]) for item in response.json()["data"]]
        assert ids.count(journal_id) == 1
