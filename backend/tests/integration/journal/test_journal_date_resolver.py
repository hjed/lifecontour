"""Integration tests for :class:`JournalDateResolver` against real PostgreSQL.

The unit tests own the calendar rules. What only a real database can show is
that the two things those rules sit on actually hold end to end:

- the journal's start comes back out of ``TIMESTAMP WITH TIME ZONE`` as an
  instant the resolver can convert, not as a bare wall time;
- the timezone the conversion uses is the one stored in ``user_settings``, with
  UTC standing in when the row is missing or holds a name the tz database does
  not know (the column has no ``CHECK`` constraint, so it can).

Journals are seeded at fixed instants rather than offsets from ``now()``: a test
that asserts a *date* cannot be anchored on a moving one.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from core_shared.models.journals import EventDateRange, Journal
from dishka import Provider, Scope, make_async_container, provide
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_date_resolver import (
    JournalDateResolver,
    journal_date,
)
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from app.infrastructure.di.contacts import ContactProvider
from app.infrastructure.di.infrastructure import InfrastructureProvider
from app.infrastructure.di.integrations import IntegrationProvider
from app.infrastructure.di.journal import JournalProvider
from app.infrastructure.di.settings import SettingsProvider
from app.infrastructure.di.tasks import TaskProvider

USER_ID = "test-user-123"

# 00:30 on 31 July in Sydney (+10), while UTC is still on the 30th.
JUST_PAST_LOCAL_MIDNIGHT = datetime(2026, 7, 30, 14, 30, tzinfo=UTC)
# 06:00 on 31 July in Sydney — the same local day, a different UTC one.
SAME_LOCAL_DAY = datetime(2026, 7, 30, 20, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    return SqlJournalRepository(async_connection)


@pytest_asyncio.fixture
async def user_settings_repository(
    async_connection: AsyncConnection,
) -> SqlUserSettingsRepository:
    return SqlUserSettingsRepository(async_connection)


@pytest_asyncio.fixture
async def resolver(
    user_settings_repository: SqlUserSettingsRepository,
) -> JournalDateResolver:
    return JournalDateResolver(user_settings_repo=user_settings_repository)


async def create_journal(
    journal_repository: SqlJournalRepository,
    *,
    start: datetime,
    user_id: str = USER_ID,
) -> Journal:
    """Persist a one-hour journal starting at ``start`` and return it as stored."""
    return await journal_repository.save(
        Journal(
            user_id=user_id,
            title="Anchor Journal",
            content="content",
            event_date_range=EventDateRange(
                start=start, end=start + timedelta(hours=1)
            ),
        )
    )


@pytest.mark.integration
class TestJournalDateResolverIntegration:
    """Resolution against real journal rows and real user settings."""

    async def test_resolves_a_journals_date_against_a_real_settings_row(
        self,
        resolver: JournalDateResolver,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
    ):
        """The stored timezone decides the date, and it is not the UTC date."""
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Australia/Sydney")
        )
        journal = await create_journal(
            journal_repository, start=JUST_PAST_LOCAL_MIDNIGHT
        )

        tz = await resolver.timezone_for(USER_ID)

        # The instant survives the round trip as an instant, not a wall time.
        assert journal.event_date_range.start.tzinfo is not None
        assert journal.event_date_range.start.astimezone(UTC).date() == date(
            2026, 7, 30
        )
        assert tz.key == "Australia/Sydney"
        assert journal_date(journal, tz) == date(2026, 7, 31)

    async def test_falls_back_to_utc_when_no_settings_row_exists(
        self,
        resolver: JournalDateResolver,
        journal_repository: SqlJournalRepository,
    ):
        """A user who never set a timezone is read in UTC, not skipped."""
        user_id = f"no-settings-{uuid4()}"
        journal = await create_journal(
            journal_repository, start=JUST_PAST_LOCAL_MIDNIGHT, user_id=user_id
        )

        tz = await resolver.timezone_for(user_id)

        assert tz.key == "UTC"
        assert journal_date(journal, tz) == date(2026, 7, 30)

    async def test_an_invalid_stored_timezone_falls_back_to_utc(
        self,
        resolver: JournalDateResolver,
        user_settings_repository: SqlUserSettingsRepository,
    ):
        """The column accepts any string, so resolution must absorb a bad one."""
        user_id = f"bad-timezone-{uuid4()}"
        await user_settings_repository.save(
            UserSettings(user_id=user_id, timezone="Mars/Olympus")
        )

        assert (await resolver.timezone_for(user_id)).key == "UTC"

    async def test_future_dating_is_decided_on_the_users_local_day(
        self,
        resolver: JournalDateResolver,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
    ):
        """A UTC reading would call this journal future-dated. In Sydney it is today."""
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Australia/Sydney")
        )
        journal = await create_journal(journal_repository, start=SAME_LOCAL_DAY)

        assert (
            await resolver.is_future_dated(
                USER_ID, journal, now=JUST_PAST_LOCAL_MIDNIGHT
            )
            is False
        )
        assert await resolver.today(USER_ID, now=JUST_PAST_LOCAL_MIDNIGHT) == date(
            2026, 7, 31
        )


@pytest.mark.integration
class TestDependencyInjection:
    """The resolver is reachable through the container, not just importable."""

    async def test_journal_provider_supplies_the_resolver(
        self, async_connection: AsyncConnection
    ):
        """Resolving it wires in the settings repository on the request connection.

        None of the other providers is a dependency of the resolver itself.
        They are here because Dishka validates the whole graph up front:
        ``JournalProvider``'s other factories need ``Settings``
        (``InfrastructureProvider``) and, since the daily-summary assembler
        began consuming the upcoming-task listing, ``TaskReadService``
        (``TaskProvider``, which reaches for ``ContactProvider``, which reaches
        for ``IntegrationProvider``). This was the one container in the repo
        that did not already register them.
        """

        class _ConnectionProvider(Provider):
            def __init__(self, connection: AsyncConnection) -> None:
                super().__init__()
                self.connection = connection

            @provide(scope=Scope.REQUEST)
            def get_connection(self) -> AsyncConnection:
                return self.connection

        container = make_async_container(
            _ConnectionProvider(async_connection),
            InfrastructureProvider(),
            ContactProvider(),
            IntegrationProvider(),
            JournalProvider(),
            TaskProvider(),
            SettingsProvider(),
        )
        try:
            async with container() as request_container:
                resolver = await request_container.get(JournalDateResolver)

                assert isinstance(resolver, JournalDateResolver)
                assert (await resolver.timezone_for(f"unknown-{uuid4()}")).key == "UTC"
        finally:
            await container.close()
