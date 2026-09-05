"""Integration tests for the home dashboard's upcoming-dates section.

Exercises ``GET /api/home-dashboard``'s fourth section against real contacts,
real ``contact_important_dates`` rows and the real importance signals, because a
read that is correct against a mock can still be asking the database for the
wrong month, ranking on nothing, or fanning out.

Three things are asserted here that no unit test reaches:

- **The row a card draws arrives whole** — the contact, the type, the resolved
  day and how far away it is — through the endpoint rather than through the
  renderer.
- **The ranking survives real signals.** Contact importance is inferred from a
  favourite flag and recent activity, and two contacts sharing a day are the
  only fixture that shows the order came from them.
- **The section windows on the day the page is anchored on**, whatever zone the
  user is in, so the dates and the agenda beside them cannot be about different
  days.

A test cannot freeze the clock through HTTP, so the dates are seeded relative to
an instant read inside the test and placed mid-window, where a midnight crossing
mid-test cannot turn a correct answer into a failure — the same bracketing the
agenda suite uses. The window's own edges are asserted where the clock *can* be
pinned, in ``tests/integration/contacts/``.
"""

import datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from tests.integration.statement_recorder import recorded_statements

URL = "/api/home-dashboard"
USER_ID = "test-user-123"

# A large positive offset, so one local day spans two UTC dates.
FAR_EAST = "Pacific/Kiritimati"  # UTC+14

pytestmark = pytest.mark.asyncio


def in_days(offset: int) -> datetime.date:
    """A day this many days after UTC's today.

    The test user has no stored timezone, so the dashboard anchors on UTC's
    today and this is the day the window is measured from.
    """
    return datetime.datetime.now(datetime.UTC).date() + datetime.timedelta(days=offset)


async def seed_contact(
    connection: AsyncConnection,
    contact_id: int,
    *,
    first_name: str = "Ada",
    last_name: str = "Lovelace",
    photo_url: str | None = None,
    is_favourite: bool = False,
) -> None:
    """A bare contact, with the display fields a row draws."""
    await connection.execute(
        text("""
            INSERT INTO contacts (
                id, first_name, last_name, photo_url, is_favourite,
                created_at, updated_at
            )
            VALUES (:id, :first_name, :last_name, :photo_url, :is_favourite,
                    NOW(), NOW())
        """),
        {
            "id": contact_id,
            "first_name": first_name,
            "last_name": last_name,
            "photo_url": photo_url,
            "is_favourite": is_favourite,
        },
    )


async def seed_date(
    connection: AsyncConnection,
    date_id: int,
    contact_id: int,
    *,
    on: datetime.date,
    year: int | None = None,
    date_type: str = "birthday",
) -> None:
    """One important date, placed on a given day of the calendar."""
    await connection.execute(
        text("""
            INSERT INTO contact_important_dates (
                id, contact_id, date_type, precision, year, month, day,
                created_at, updated_at
            )
            VALUES (:id, :contact_id, :date_type, :precision, :year, :month,
                    :day, NOW(), NOW())
        """),
        {
            "id": date_id,
            "contact_id": contact_id,
            "date_type": date_type,
            "precision": "full" if year else "day_month",
            "year": year,
            "month": on.month,
            "day": on.day,
        },
    )


def section_of(response: Any) -> dict[str, Any]:
    """The upcoming-dates section's envelope."""
    assert response.status_code == 200
    section: dict[str, Any] = response.json()["data"]["attributes"]["upcoming_dates"]
    return section


def dates_of(response: Any) -> list[dict[str, Any]]:
    """The rows in the section, in the order they were sent."""
    section = section_of(response)
    assert section["status"] == "ready", section
    return list(section["data"]["dates"])


class TestWhatReachesTheSection:
    async def test_a_date_in_the_window_arrives_with_everything_the_row_draws(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        occurs_on = in_days(3)
        await seed_contact(
            async_connection,
            1,
            first_name="Ada",
            last_name="Lovelace",
            photo_url="https://example.test/ada.png",
        )
        await seed_date(async_connection, 10, 1, on=occurs_on, year=1991)

        response = await authenticated_client.get(URL)
        [row] = dates_of(response)

        anchor = datetime.date.fromisoformat(response.json()["meta"]["anchor"]["date"])
        assert row["contact_id"] == 1
        assert row["contact_name"] == "Ada Lovelace"
        assert row["photo_url"] == "https://example.test/ada.png"
        assert row["date_type"] == "birthday"
        assert row["custom_date_type_name"] is None
        assert row["occurs_on"] == occurs_on.isoformat()
        assert row["days_away"] == (occurs_on - anchor).days
        assert row["years"] == occurs_on.year - 1991
        assert row["observed_for_leap_day"] is False

    async def test_a_date_beyond_the_window_never_appears(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        await seed_contact(async_connection, 1)
        await seed_date(async_connection, 10, 1, on=in_days(20))

        assert dates_of(await authenticated_client.get(URL)) == []

    async def test_a_year_precision_date_never_appears(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """It records a year and no day, so there is nothing to place in a week."""
        await seed_contact(async_connection, 1)
        await async_connection.execute(
            text("""
                INSERT INTO contact_important_dates (
                    id, contact_id, date_type, precision, year,
                    created_at, updated_at
                )
                VALUES (10, 1, 'first_met', 'year', 2019, NOW(), NOW())
            """)
        )

        assert dates_of(await authenticated_client.get(URL)) == []

    async def test_a_day_month_date_shows_without_a_derived_count(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """W31 degrades the badge to the bare type, and the wire says why."""
        await seed_contact(async_connection, 1)
        await seed_date(async_connection, 10, 1, on=in_days(3))

        [row] = dates_of(await authenticated_client.get(URL))

        assert row["years"] is None


class TestTheOrder:
    async def test_the_soonest_date_leads(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        await seed_contact(async_connection, 1, first_name="Later")
        await seed_contact(async_connection, 2, first_name="Sooner")
        await seed_date(async_connection, 10, 1, on=in_days(5))
        await seed_date(async_connection, 11, 2, on=in_days(2))

        rows = dates_of(await authenticated_client.get(URL))

        assert [row["contact_id"] for row in rows] == [2, 1]

    async def test_a_favourite_leads_a_shared_day(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """The only fixture that shows the order came from the real signals."""
        shared_day = in_days(3)
        await seed_contact(async_connection, 1, first_name="Ordinary")
        await seed_contact(
            async_connection, 2, first_name="Favourite", is_favourite=True
        )
        await seed_date(async_connection, 10, 1, on=shared_day)
        await seed_date(async_connection, 11, 2, on=shared_day)

        rows = dates_of(await authenticated_client.get(URL))

        assert [row["contact_id"] for row in rows] == [2, 1]

    async def test_importance_never_reorders_the_days(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """The pair with the test above: a favourite whose date is later stays
        later, so importance is proved to break ties rather than rank the list."""
        await seed_contact(async_connection, 1, first_name="Ordinary")
        await seed_contact(
            async_connection, 2, first_name="Favourite", is_favourite=True
        )
        await seed_date(async_connection, 10, 1, on=in_days(2))
        await seed_date(async_connection, 11, 2, on=in_days(5))

        rows = dates_of(await authenticated_client.get(URL))

        assert [row["contact_id"] for row in rows] == [1, 2]


class TestTheSectionsOwnAnswers:
    async def test_nothing_in_the_window_is_ready_and_empty(
        self, authenticated_client: AsyncClient
    ) -> None:
        """W29's idiom — one quiet line — not the section being unavailable."""
        section = section_of(await authenticated_client.get(URL))

        assert section["status"] == "ready"
        assert section["data"]["dates"] == []
        assert section["data"]["total"] == 0

    async def test_the_total_names_the_whole_window(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """The card renders three rows and its show-more names this."""
        for offset in range(1, 6):
            await seed_contact(async_connection, offset, first_name=f"Contact{offset}")
            await seed_date(async_connection, 10 + offset, offset, on=in_days(offset))

        section = section_of(await authenticated_client.get(URL))

        assert section["data"]["total"] == 5
        assert len(section["data"]["dates"]) == 5

    async def test_the_window_travels_with_the_rows(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.get(URL)
        window = section_of(response)["data"]["window"]

        anchor = response.json()["meta"]["anchor"]["date"]
        assert window["start_date"] == anchor
        assert window["days_ahead"] == 7
        assert (
            window["end_date"]
            == (
                datetime.date.fromisoformat(anchor) + datetime.timedelta(days=7)
            ).isoformat()
        )

    async def test_it_matches_the_page_anchor_in_a_far_eastern_zone(
        self,
        authenticated_client: AsyncClient,
        user_settings_repository: SqlUserSettingsRepository,
    ) -> None:
        """Kiritimati is a day ahead of UTC for part of every day. Whichever day
        it is there, the section must be about the same one the page is — a
        section resolving its own anchor could disagree with the agenda beside
        it, and this is what makes the anchor being handed down observable.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=FAR_EAST)
        )

        response = await authenticated_client.get(URL)

        meta = response.json()["meta"]["anchor"]
        assert meta["timezone"] == FAR_EAST
        assert section_of(response)["data"]["window"]["start_date"] == meta["date"]


class TestTheRoundTrips:
    async def test_the_section_costs_two_statements_however_many_dates(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """An N+1 here is a per-contact round trip on a page load.

        The count is of the *whole* request, so it is asserted as a difference:
        five contacts must cost exactly what one costs.
        """
        await seed_contact(async_connection, 1)
        await seed_date(async_connection, 10, 1, on=in_days(3))

        with recorded_statements(async_connection) as one_contact:
            await authenticated_client.get(URL)

        for offset in range(2, 7):
            await seed_contact(async_connection, offset, first_name=f"Contact{offset}")
            await seed_date(async_connection, 10 + offset, offset, on=in_days(3))

        with recorded_statements(async_connection) as six_contacts:
            response = await authenticated_client.get(URL)

        assert len(dates_of(response)) == 6
        assert len(six_contacts) == len(one_contact)
