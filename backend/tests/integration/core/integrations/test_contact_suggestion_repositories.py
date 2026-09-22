"""Integration tests for the contact-suggestion repositories.

``SqlUnmatchedParticipantEmailRepository`` aggregates recorded unmatched
participant emails into suggestions; ``SqlContactSuggestionIgnoreRepository``
holds the per-user ignore list those suggestions exclude.
"""

from datetime import datetime

import pytest
from core_shared.models.history import Provenance
from core_shared.models.journals.attendee_status import AttendeeStatus
from core_shared.models.journals.journal_relationship_types import (
    JournalContactRelationshipType,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.contact_suggestion_ignore_repository import (
    SqlContactSuggestionIgnoreRepository,
)
from app.core.integrations.adapters.sql.unmatched_participant_email_repository import (
    SqlUnmatchedParticipantEmailRepository,
)
from tests.integration.core.integrations.contact_suggestion_seeding import (
    OTHER_USER_ID,
    USER_ID,
    create_contact,
    create_journal,
    record_unmatched,
    seed_participant,
    unmatched_journal_ids,
)

MIN_JOURNALS = 5


@pytest.mark.integration
class TestListCandidates:
    async def test_email_on_enough_journals_is_a_candidate(
        self, async_connection: AsyncConnection
    ) -> None:
        await seed_participant(
            async_connection, "often@x.com", 5, display_name="Often Seen"
        )
        await seed_participant(async_connection, "rarely@x.com", 4)

        candidates = await SqlUnmatchedParticipantEmailRepository(
            async_connection
        ).list_candidates(USER_ID, MIN_JOURNALS)

        assert [(c.email, c.display_name, c.event_count) for c in candidates] == [
            ("often@x.com", "Often Seen", 5)
        ]

    async def test_last_seen_is_the_most_recent_journal(
        self, async_connection: AsyncConnection
    ) -> None:
        journal_ids = await seed_participant(async_connection, "often@x.com", 5)

        [candidate] = await SqlUnmatchedParticipantEmailRepository(
            async_connection
        ).list_candidates(USER_ID, MIN_JOURNALS)

        # seed_participant dates journal i at i + 1 days ago.
        assert candidate.last_seen_at == await _journal_start(
            async_connection, journal_ids[0]
        )

    async def test_candidates_are_ordered_by_event_count(
        self, async_connection: AsyncConnection
    ) -> None:
        await seed_participant(async_connection, "five@x.com", 5)
        await seed_participant(async_connection, "seven@x.com", 7)

        candidates = await SqlUnmatchedParticipantEmailRepository(
            async_connection
        ).list_candidates(USER_ID, MIN_JOURNALS)

        assert [c.email for c in candidates] == ["seven@x.com", "five@x.com"]

    async def test_other_users_journals_do_not_count(
        self, async_connection: AsyncConnection
    ) -> None:
        await seed_participant(async_connection, "shared@x.com", 3)
        await seed_participant(
            async_connection, "shared@x.com", 3, user_id=OTHER_USER_ID
        )

        candidates = await SqlUnmatchedParticipantEmailRepository(
            async_connection
        ).list_candidates(USER_ID, MIN_JOURNALS)

        assert candidates == []

    async def test_email_held_by_a_contact_in_any_case_is_excluded(
        self, async_connection: AsyncConnection
    ) -> None:
        await seed_participant(async_connection, "jane@x.com", 5)
        await create_contact(async_connection, email="Jane@X.com")

        candidates = await SqlUnmatchedParticipantEmailRepository(
            async_connection
        ).list_candidates(USER_ID, MIN_JOURNALS)

        assert candidates == []

    async def test_ignored_email_is_excluded_for_that_user_only(
        self, async_connection: AsyncConnection
    ) -> None:
        await seed_participant(async_connection, "noisy@x.com", 5)
        await seed_participant(
            async_connection, "noisy@x.com", 5, user_id=OTHER_USER_ID
        )
        await SqlContactSuggestionIgnoreRepository(async_connection).ignore(
            USER_ID, "noisy@x.com", Provenance.UI
        )

        repo = SqlUnmatchedParticipantEmailRepository(async_connection)
        assert await repo.list_candidates(USER_ID, MIN_JOURNALS) == []
        assert [
            c.email for c in await repo.list_candidates(OTHER_USER_ID, MIN_JOURNALS)
        ] == ["noisy@x.com"]


@pytest.mark.integration
class TestForEmail:
    async def test_list_for_email_returns_the_users_rows(
        self, async_connection: AsyncConnection
    ) -> None:
        mine = await create_journal(async_connection)
        theirs = await create_journal(async_connection, user_id=OTHER_USER_ID)
        await record_unmatched(
            async_connection, mine, "jane@x.com", status="ATTENDING", role="ORGANISER"
        )
        await record_unmatched(async_connection, theirs, "jane@x.com")

        rows = await SqlUnmatchedParticipantEmailRepository(
            async_connection
        ).list_for_email(USER_ID, "jane@x.com")

        assert [(r.journal_id, r.relationship_type, r.status) for r in rows] == [
            (mine, JournalContactRelationshipType.INVITEE, AttendeeStatus.ATTENDING)
        ]

    async def test_delete_for_email_leaves_other_users_rows(
        self, async_connection: AsyncConnection
    ) -> None:
        mine = await create_journal(async_connection)
        theirs = await create_journal(async_connection, user_id=OTHER_USER_ID)
        await record_unmatched(async_connection, mine, "jane@x.com")
        await record_unmatched(async_connection, theirs, "jane@x.com")

        await SqlUnmatchedParticipantEmailRepository(async_connection).delete_for_email(
            USER_ID, "jane@x.com"
        )

        assert await unmatched_journal_ids(async_connection, "jane@x.com") == {theirs}


@pytest.mark.integration
class TestIgnoreList:
    async def test_ignore_is_idempotent_and_listed(
        self, async_connection: AsyncConnection
    ) -> None:
        repo = SqlContactSuggestionIgnoreRepository(async_connection)

        await repo.ignore(USER_ID, "noisy@x.com", Provenance.UI)
        await repo.ignore(USER_ID, "noisy@x.com", Provenance.MCP)

        ignored = await repo.list_ignored(USER_ID)
        assert [(i.email, i.provenance) for i in ignored] == [
            ("noisy@x.com", Provenance.UI)
        ]
        assert await repo.list_ignored(OTHER_USER_ID) == []

    async def test_unignore_reports_whether_anything_was_removed(
        self, async_connection: AsyncConnection
    ) -> None:
        repo = SqlContactSuggestionIgnoreRepository(async_connection)
        await repo.ignore(USER_ID, "noisy@x.com", Provenance.UI)

        assert await repo.unignore(USER_ID, "noisy@x.com") is True
        assert await repo.unignore(USER_ID, "noisy@x.com") is False
        assert await repo.list_ignored(USER_ID) == []


async def _journal_start(connection: AsyncConnection, journal_id: int) -> datetime:
    result = await connection.execute(
        text("SELECT event_date_range_start FROM journals WHERE id = :id"),
        {"id": journal_id},
    )
    start: datetime = result.scalar_one()
    return start
