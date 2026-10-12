"""Integration tests: ``MergedAliasRepository`` is how a merged record is found.

Workers ask in the payload's terms (``'google'``, ``'strava:<id>'``), the merge
records in the link store's terms (``'google_calendar'``, ``'<id>'``); both have
to reach the same row, and only the owner's.
"""

import uuid

import pytest
from core_shared.repositories.merged_alias_repository import (
    ExternalRecord,
    MergedAliasRepository,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

USER_ID = "alias-repo-user"
OTHER_USER_ID = "alias-repo-other"


async def _journal(connection: AsyncConnection, user_id: str = USER_ID) -> int:
    result = await connection.execute(
        text("""
            INSERT INTO journals
                (user_id, title, content,
                 event_date_range_start, event_date_range_end)
            VALUES (:user_id, 'Pilates', '', now(), now() + interval '1 hour')
            RETURNING id
        """),
        {"user_id": user_id},
    )
    return int(result.scalar_one())


async def _calendar(connection: AsyncConnection) -> uuid.UUID:
    calendar_id = uuid.uuid4()
    await connection.execute(
        text("""
            INSERT INTO calendars (id, user_id, name, color)
            VALUES (:id, :user_id, 'Work', '#336699')
        """),
        {"id": calendar_id, "user_id": USER_ID},
    )
    return calendar_id


@pytest.mark.integration
class TestMergedAliasRepository:
    async def test_a_recorded_alias_is_found_by_the_payload_name_and_id(
        self, clean_database: AsyncConnection
    ) -> None:
        conn = clean_database
        survivor = await _journal(conn)
        calendar_id = await _calendar(conn)
        repo = MergedAliasRepository(conn)

        await repo.record_aliases(
            journal_id=survivor,
            user_id=USER_ID,
            records=[
                ExternalRecord(
                    integration_source="google_calendar",
                    external_id="dm1q_20260904T021500Z",
                    calendar_id=calendar_id,
                    external_identity="google:dm1q:20260904T021500Z",
                    recurring_event_id="dm1q",
                ),
                ExternalRecord(integration_source="strava", external_id="222"),
            ],
        )

        google = await repo.find_alias(
            user_id=USER_ID,
            payload_source="google",
            external_id="dm1q_20260904T021500Z",
        )
        strava = await repo.find_alias(
            user_id=USER_ID, payload_source="strava", external_id="strava:222"
        )

        assert google is not None
        assert google.journal_id == survivor
        assert google.calendar_id == calendar_id
        assert google.recurring_event_id == "dm1q"
        assert strava is not None
        assert strava.journal_id == survivor

    async def test_an_alias_is_found_by_identity_from_any_calendar(
        self, clean_database: AsyncConnection
    ) -> None:
        """Another calendar's copy of the absorbed event is the same event."""
        conn = clean_database
        survivor = await _journal(conn)
        repo = MergedAliasRepository(conn)
        await repo.record_aliases(
            journal_id=survivor,
            user_id=USER_ID,
            records=[
                ExternalRecord(
                    integration_source="google_calendar",
                    external_id="work-copy",
                    external_identity="shared-token",
                )
            ],
        )

        found = await repo.find_alias(
            user_id=USER_ID,
            payload_source="google",
            external_id="personal-copy",
            external_identity="shared-token",
        )

        assert found is not None
        assert found.journal_id == survivor

    async def test_another_users_alias_is_never_found(
        self, clean_database: AsyncConnection
    ) -> None:
        conn = clean_database
        theirs = await _journal(conn, OTHER_USER_ID)
        repo = MergedAliasRepository(conn)
        await repo.record_aliases(
            journal_id=theirs,
            user_id=OTHER_USER_ID,
            records=[
                ExternalRecord(
                    integration_source="google_calendar",
                    external_id="evt",
                    external_identity="token",
                )
            ],
        )

        assert (
            await repo.find_alias(
                user_id=USER_ID,
                payload_source="google",
                external_id="evt",
                external_identity="token",
            )
            is None
        )

    async def test_recording_an_alias_twice_keeps_the_first(
        self, clean_database: AsyncConnection
    ) -> None:
        conn = clean_database
        first = await _journal(conn)
        second = await _journal(conn)
        repo = MergedAliasRepository(conn)
        record = ExternalRecord(integration_source="strava", external_id="222")

        await repo.record_aliases(journal_id=first, user_id=USER_ID, records=[record])
        await repo.record_aliases(journal_id=second, user_id=USER_ID, records=[record])

        found = await repo.find_alias(
            user_id=USER_ID, payload_source="strava", external_id="222"
        )
        assert found is not None
        assert found.journal_id == first

    async def test_repointing_moves_every_alias_to_the_new_survivor(
        self, clean_database: AsyncConnection
    ) -> None:
        conn = clean_database
        absorbed = await _journal(conn)
        survivor = await _journal(conn)
        repo = MergedAliasRepository(conn)
        await repo.record_aliases(
            journal_id=absorbed,
            user_id=USER_ID,
            records=[
                ExternalRecord(integration_source="immich_album", external_id="a")
            ],
        )

        await repo.repoint_aliases(
            source_journal_id=absorbed, target_journal_id=survivor
        )

        assert [
            alias.external_id for alias in await repo.aliases_for_journal(survivor)
        ] == ["a"]
        assert await repo.aliases_for_journal(absorbed) == []

    async def test_an_unaliasable_source_finds_nothing(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = MergedAliasRepository(clean_database)

        assert (
            await repo.find_alias(
                user_id=USER_ID, payload_source="snipeit_checkout", external_id="x"
            )
            is None
        )


@pytest.mark.integration
class TestMergedAliasLocks:
    async def test_a_merge_and_a_sync_can_both_hold_a_record_in_one_transaction(
        self, clean_database: AsyncConnection
    ) -> None:
        """The locks are transaction-scoped and re-entrant for their holder.

        Contention between two transactions is PostgreSQL's to guarantee; what
        this pins is that both sides' calls are valid SQL and that a holder
        taking a key twice — a merge that is also syncing — does not block on
        itself.
        """
        repo = MergedAliasRepository(clean_database)
        record = ExternalRecord(
            integration_source="google_calendar",
            external_id="evt-1",
            external_identity="token",
        )

        await repo.lock_records(user_id=USER_ID, records=[record, record])
        await repo.lock_record(
            user_id=USER_ID,
            payload_source="google",
            external_id="evt-1",
            external_identity="token",
        )

        held = await clean_database.execute(
            text(
                "SELECT count(*) FROM pg_locks "
                "WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
            )
        )
        assert held.scalar_one() == 2
