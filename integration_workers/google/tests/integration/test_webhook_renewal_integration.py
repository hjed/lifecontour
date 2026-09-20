"""Integration tests for the calendar watch-channel renewal query.

``CalendarWatchRepository.select_due_for_renewal`` joins ``calendars``,
``user_google_auth`` and ``calendar_sync_tokens`` to decide which push channels
are close enough to expiry to re-register, and which Google account each should
be renewed under. That decision is pure SQL, so it is exercised here against a
real database rather than mocked.
"""

from datetime import UTC, datetime, timedelta

import pytest
from core_shared.repositories import CalendarWatchRenewal, CalendarWatchRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Renewal horizon used by every case below: a channel expiring inside this
# window is due, one expiring after it is not.
THRESHOLD = timedelta(hours=48)

USER_ID = "renew-user-1"
ACCOUNT_EMAIL = "renewal@example.com"


async def seed_google_account(session: AsyncSession, user_id: str, email: str) -> None:
    """Insert the Google OAuth row the renewal query reads the account from."""
    await session.execute(
        text("""
            INSERT INTO user_google_auth
                (user_id, google_account_email, encrypted_access_token,
                 encrypted_refresh_token, expires_at, created_at, updated_at)
            VALUES (:user_id, :email, :token, :refresh, :now, :now, :now)
            ON CONFLICT (user_id, google_account_email) DO NOTHING
        """),
        {
            "user_id": user_id,
            "email": email,
            "token": b"encrypted-access",
            "refresh": b"encrypted-refresh",
            "now": datetime.now(UTC),
        },
    )


async def seed_calendar(
    session: AsyncSession,
    user_id: str,
    google_calendar_id: str,
    *,
    is_synced: bool = True,
) -> None:
    """Insert a calendar, optionally one that is not synced to Google."""
    await session.execute(
        text("""
            INSERT INTO calendars
                (user_id, name, color, is_synced_to_google, google_calendar_id)
            VALUES (:user_id, :name, '#336699', :is_synced, :google_calendar_id)
        """),
        {
            "user_id": user_id,
            "name": f"Calendar {google_calendar_id}",
            "is_synced": is_synced,
            "google_calendar_id": google_calendar_id,
        },
    )


async def seed_channel(
    session: AsyncSession,
    user_id: str,
    email: str,
    google_calendar_id: str,
    *,
    expiration: datetime | None,
) -> None:
    """Insert a calendar_sync_tokens row carrying a watch channel."""
    await session.execute(
        text("""
            INSERT INTO calendar_sync_tokens
                (user_id, google_account_email, google_calendar_id,
                 channel_id, channel_resource_id, channel_expiration,
                 created_at, updated_at)
            VALUES (:user_id, :email, :google_calendar_id,
                    :channel_id, :resource_id, :expiration, :now, :now)
        """),
        {
            "user_id": user_id,
            "email": email,
            "google_calendar_id": google_calendar_id,
            "channel_id": f"channel-{google_calendar_id}",
            "resource_id": f"resource-{google_calendar_id}",
            "expiration": expiration,
            "now": datetime.now(UTC),
        },
    )


async def select_due(
    session: AsyncSession, deadline: datetime
) -> list[CalendarWatchRenewal]:
    """Run the renewal query against the test session's connection."""
    conn = await session.connection()
    return await CalendarWatchRepository(conn).select_due_for_renewal(deadline)


@pytest.mark.asyncio
class TestSelectCalendarsDueForRenewal:
    """The renewal query returns exactly the calendars whose channel is lapsing."""

    async def test_selects_only_calendars_whose_channel_is_lapsing(
        self, db_session: AsyncSession
    ) -> None:
        """Expiring, expired, unregistered and unknown-expiry channels are due.

        Channels comfortably in the future, and calendars that are not synced
        to Google at all, are left alone.
        """
        now = datetime.now(UTC)
        await seed_google_account(db_session, USER_ID, ACCOUNT_EMAIL)

        # Due: expires inside the 48h window.
        await seed_calendar(db_session, USER_ID, "cal-expiring")
        await seed_channel(
            db_session,
            USER_ID,
            ACCOUNT_EMAIL,
            "cal-expiring",
            expiration=now + timedelta(hours=6),
        )

        # Due: already expired.
        await seed_calendar(db_session, USER_ID, "cal-expired")
        await seed_channel(
            db_session,
            USER_ID,
            ACCOUNT_EMAIL,
            "cal-expired",
            expiration=now - timedelta(days=1),
        )

        # Due: never registered — no calendar_sync_tokens row at all.
        await seed_calendar(db_session, USER_ID, "cal-unregistered")

        # Due: a token row exists but records no expiry.
        await seed_calendar(db_session, USER_ID, "cal-unknown-expiry")
        await seed_channel(
            db_session,
            USER_ID,
            ACCOUNT_EMAIL,
            "cal-unknown-expiry",
            expiration=None,
        )

        # Not due: expires well beyond the window.
        await seed_calendar(db_session, USER_ID, "cal-fresh")
        await seed_channel(
            db_session,
            USER_ID,
            ACCOUNT_EMAIL,
            "cal-fresh",
            expiration=now + timedelta(days=6),
        )

        # Not due: expiring imminently, but the calendar is not synced.
        await seed_calendar(db_session, USER_ID, "cal-unsynced", is_synced=False)
        await seed_channel(
            db_session,
            USER_ID,
            ACCOUNT_EMAIL,
            "cal-unsynced",
            expiration=now + timedelta(hours=1),
        )

        await db_session.commit()

        due = await select_due(db_session, now + THRESHOLD)

        due_ids = {row.google_calendar_id for row in due if row.user_id == USER_ID}
        assert due_ids == {
            "cal-expiring",
            "cal-expired",
            "cal-unregistered",
            "cal-unknown-expiry",
        }

    async def test_returns_the_account_email_for_each_calendar(
        self, db_session: AsyncSession
    ) -> None:
        """Rows carry everything setup_calendar_webhook needs to run."""
        now = datetime.now(UTC)
        user_id = "renew-user-2"
        email = "renewal-2@example.com"

        await seed_google_account(db_session, user_id, email)
        await seed_calendar(db_session, user_id, "cal-2")
        await db_session.commit()

        due = await select_due(db_session, now + THRESHOLD)

        rows = [row for row in due if row.user_id == user_id]
        assert rows == [
            CalendarWatchRenewal(
                user_id=user_id,
                google_account_email=email,
                google_calendar_id="cal-2",
            )
        ]

    async def test_a_user_with_two_google_accounts_yields_one_row_per_calendar(
        self, db_session: AsyncSession
    ) -> None:
        """The account join must not fan a single calendar out into duplicates.

        ``user_google_auth`` is unique on (user_id, google_account_email), so a
        user can hold more than one Google account. A calendar records no
        account of its own, and registering the same calendar twice would
        create two competing channels for it.
        """
        now = datetime.now(UTC)
        user_id = "renew-user-3"

        await seed_google_account(db_session, user_id, "aaa@example.com")
        await seed_google_account(db_session, user_id, "zzz@example.com")
        await seed_calendar(db_session, user_id, "cal-3")
        await db_session.commit()

        due = await select_due(db_session, now + THRESHOLD)

        rows = [row for row in due if row.user_id == user_id]
        assert len(rows) == 1
        assert rows[0].google_calendar_id == "cal-3"

    async def test_renews_under_the_account_the_channel_was_registered_with(
        self, db_session: AsyncSession
    ) -> None:
        """A calendar keeps the account its existing channel belongs to.

        Picking any other connected account would register a second, competing
        channel under different credentials while the real one expired
        unrenewed.
        """
        now = datetime.now(UTC)
        user_id = "renew-user-4"

        # The alphabetically first account is deliberately NOT the one the
        # channel was registered under.
        await seed_google_account(db_session, user_id, "aaa@example.com")
        await seed_google_account(db_session, user_id, "zzz@example.com")
        await seed_calendar(db_session, user_id, "cal-4")
        await seed_channel(
            db_session,
            user_id,
            "zzz@example.com",
            "cal-4",
            expiration=now + timedelta(hours=6),
        )
        await db_session.commit()

        due = await select_due(db_session, now + THRESHOLD)

        rows = [row for row in due if row.user_id == user_id]
        assert rows == [
            CalendarWatchRenewal(
                user_id=user_id,
                google_account_email="zzz@example.com",
                google_calendar_id="cal-4",
            )
        ]

    async def test_falls_back_when_the_channels_account_was_disconnected(
        self, db_session: AsyncSession
    ) -> None:
        """A channel whose account is gone is re-registered under a live one.

        Keeping the disconnected account would renew forever against
        credentials that no longer exist.
        """
        now = datetime.now(UTC)
        user_id = "renew-user-5"

        await seed_google_account(db_session, user_id, "live@example.com")
        await seed_calendar(db_session, user_id, "cal-5")
        # A channel left behind by an account that is no longer connected:
        # there is no matching user_google_auth row for it.
        await seed_channel(
            db_session,
            user_id,
            "disconnected@example.com",
            "cal-5",
            expiration=now + timedelta(days=6),
        )
        await db_session.commit()

        due = await select_due(db_session, now + THRESHOLD)

        rows = [row for row in due if row.user_id == user_id]
        assert rows == [
            CalendarWatchRenewal(
                user_id=user_id,
                google_account_email="live@example.com",
                google_calendar_id="cal-5",
            )
        ]

    async def test_user_with_no_connected_account_is_never_returned(
        self, db_session: AsyncSession
    ) -> None:
        """A synced calendar with no Google account behind it cannot be renewed."""
        now = datetime.now(UTC)
        user_id = "renew-user-6"

        await seed_calendar(db_session, user_id, "cal-6")
        await db_session.commit()

        due = await select_due(db_session, now + THRESHOLD)

        assert [row for row in due if row.user_id == user_id] == []
