"""
SQL repository for Google Calendar push notification watch channels.

Watch channels are registered per calendar and expire after their TTL (7 days),
after which Google discards them and silently stops delivering notifications.
This repository answers the question the renewal cron asks: which synced
calendars have a channel close enough to expiry to be re-registered?
"""

from datetime import datetime
from typing import NamedTuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class CalendarWatchRenewal(NamedTuple):
    """A calendar whose Google push notification channel needs re-registering."""

    user_id: str
    google_account_email: str
    google_calendar_id: str


class CalendarWatchRepository:
    """Repository for reading calendar watch-channel state."""

    def __init__(self, conn: AsyncConnection):
        """
        Initialize the repository.

        Args:
            conn: Database connection
        """
        self.conn = conn

    async def lock_calendar(self, user_id: str, google_calendar_id: str) -> None:
        """
        Serialise watch-channel setup for one calendar.

        Registering a channel is read-then-write across two Google API calls, so
        two overlapping runs for the same calendar — a scheduled renewal meeting
        a manual re-registration, say — can each stop the old channel and
        register a replacement. Only one survives the upsert; the other stays
        live at Google and delivers notifications the webhook endpoint rejects
        until it expires.

        The key is the calendar, deliberately **not** the Google account. The
        account is an attribute of the channel being written rather than part of
        the resource being protected, and callers disagree about it: renewal
        uses the account the existing channel was registered under, while manual
        re-registration picks one of the user's accounts unordered. Including it
        would hand those two runs different locks — exactly the concurrent pair
        this exists to prevent.

        The lock is transaction-scoped: it is released by the caller's commit or
        rollback, so it must be taken inside the same transaction that writes
        the channel, and it deliberately spans the Google calls in between.

        Args:
            user_id: Owner of the calendar
            google_calendar_id: The Google Calendar being registered
        """
        stmt = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
        await self.conn.execute(stmt, {"key": f"{user_id}:{google_calendar_id}"})

    async def select_due_for_renewal(
        self, deadline: datetime
    ) -> list[CalendarWatchRenewal]:
        """
        Find synced calendars whose watch channel expires before ``deadline``.

        A calendar is due when its channel is lapsing, was never registered, or
        has no recorded expiry — all three leave push notifications unreliable.

        This is a system-wide sweep run by a cron rather than on behalf of a
        signed-in user, so it deliberately spans users; the ``user_id`` it
        returns is what scopes the per-calendar job it feeds.

        Choosing the Google account for each calendar takes care, because
        ``calendars`` records none of its own and ``user_google_auth`` is unique
        on (user_id, google_account_email) rather than on user_id:

        - Prefer the account the calendar's **existing channel** was registered
          under. Renewing under a different account would leave the real channel
          to expire while writing a second, competing token row.
        - Ignore a recorded channel whose account has since been disconnected,
          so the calendar falls back to an account that can still serve it.
        - Fall back to one deterministically chosen connected account, so a user
          with several accounts cannot fan one calendar out into competing
          channels.

        Args:
            deadline: Renew channels expiring before this instant

        Returns:
            One row per calendar due for renewal, ordered by user and calendar
        """
        stmt = text("""
            WITH connected_channels AS (
                SELECT DISTINCT ON (t.user_id, t.google_calendar_id)
                       t.user_id,
                       t.google_calendar_id,
                       t.google_account_email,
                       t.channel_id,
                       t.channel_expiration
                FROM calendar_sync_tokens t
                JOIN user_google_auth g
                  ON g.user_id = t.user_id
                 AND g.google_account_email = t.google_account_email
                ORDER BY t.user_id,
                         t.google_calendar_id,
                         t.channel_expiration DESC NULLS LAST
            ),
            fallback_accounts AS (
                SELECT DISTINCT ON (user_id) user_id, google_account_email
                FROM user_google_auth
                ORDER BY user_id, google_account_email
            )
            SELECT c.user_id,
                   COALESCE(ch.google_account_email, fa.google_account_email)
                       AS google_account_email,
                   c.google_calendar_id
            FROM calendars c
            LEFT JOIN connected_channels ch
                   ON ch.user_id = c.user_id
                  AND ch.google_calendar_id = c.google_calendar_id
            LEFT JOIN fallback_accounts fa
                   ON fa.user_id = c.user_id
            WHERE c.is_synced_to_google = true
              AND c.google_calendar_id IS NOT NULL
              AND COALESCE(ch.google_account_email, fa.google_account_email)
                  IS NOT NULL
              AND (
                  ch.channel_id IS NULL
                  OR ch.channel_expiration IS NULL
                  OR ch.channel_expiration < :deadline
              )
            ORDER BY c.user_id, c.google_calendar_id
        """)
        result = await self.conn.execute(stmt, {"deadline": deadline})
        return [
            CalendarWatchRenewal(
                user_id=row.user_id,
                google_account_email=row.google_account_email,
                google_calendar_id=row.google_calendar_id,
            )
            for row in result.fetchall()
        ]
