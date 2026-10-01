"""The shared importance read, against a real database.

These assert the contract two callers now depend on: the search indexer, which
must keep producing the documents it produced before the computation moved here,
and the home dashboard, which orders upcoming important dates by it and must be
able to do so with MeiliSearch down.

The window boundary is asserted with ``now`` pinned rather than left to the
clock, because "thirty days ago" is only a testable edge if the test knows where
the edge is.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_importance_repository import (
    SqlContactImportanceRepository,
)
from app.core.contacts.models.importance import IMPORTANCE_WINDOW_DAYS
from tests.integration.contact_seeding import seed_contact
from tests.integration.statement_recorder import recorded_statements

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 6, 15, 9, 30, tzinfo=UTC)
CUTOFF = NOW - timedelta(days=IMPORTANCE_WINDOW_DAYS)


@pytest.fixture
def repository(async_connection: AsyncConnection) -> SqlContactImportanceRepository:
    """The read under test, on the test's savepoint connection."""
    return SqlContactImportanceRepository(async_connection)


async def _contact(
    connection: AsyncConnection,
    contact_id: int,
    *,
    is_favourite: bool = False,
    updated_at: datetime = NOW,
) -> None:
    """A bare contact, with its own timestamps under the test's control."""
    await seed_contact(
        connection,
        contact_id=contact_id,
        first_name="Contact",
        is_favourite=is_favourite,
        created_at=updated_at,
        updated_at=updated_at,
    )


async def _journal(
    connection: AsyncConnection,
    journal_id: int,
    contact_id: int,
    *,
    created_at: datetime,
) -> None:
    """A journal mentioning the contact, created at a chosen instant."""
    await connection.execute(
        text("""
            INSERT INTO journals (
                id, user_id, title, content,
                event_date_range_start, event_date_range_end, created_at, updated_at
            )
            VALUES (:id, 'user1', 'Journal', 'Notes', :created_at, :created_at,
                    :created_at, :created_at)
        """),
        {"id": journal_id, "created_at": created_at},
    )
    await connection.execute(
        text("""
            INSERT INTO journal_contact_relationships
                (journal_id, contact_id, relationship_type)
            VALUES (:journal_id, :contact_id, 'MENTION')
        """),
        {"journal_id": journal_id, "contact_id": contact_id},
    )


async def _history(
    connection: AsyncConnection,
    *,
    entity_type: str,
    entity_id: int,
    created_at: datetime,
) -> None:
    """One recorded field change against a contact or one of its children."""
    await connection.execute(
        text("""
            INSERT INTO field_history
                (entity_type, entity_id, field_name, new_value, created_at)
            VALUES (:entity_type, :entity_id, 'field', 'value', :created_at)
        """),
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "created_at": created_at,
        },
    )


async def _contact_method(
    connection: AsyncConnection, method_id: int, contact_id: int
) -> None:
    """One contact method, with its id under the test's control."""
    await connection.execute(
        text("""
            INSERT INTO contact_methods
                (id, contact_id, method_type, value, created_at, updated_at)
            VALUES (:id, :contact_id, 'email', 'someone@example.com', :now, :now)
        """),
        {"id": method_id, "contact_id": contact_id, "now": NOW},
    )


async def _contact_note(
    connection: AsyncConnection, note_id: int, contact_id: int
) -> None:
    """One contact note, with its id under the test's control."""
    await connection.execute(
        text("""
            INSERT INTO contact_notes (id, contact_id, content, created_at, updated_at)
            VALUES (:id, :contact_id, 'A note', :now, :now)
        """),
        {"id": note_id, "contact_id": contact_id, "now": NOW},
    )


class TestTheWindow:
    """What "recent" includes, exactly."""

    async def test_counts_rows_inside_the_window_and_not_outside_it(
        self,
        async_connection: AsyncConnection,
        repository: SqlContactImportanceRepository,
    ) -> None:
        """A second either side of the cutoff decides whether a row counts."""
        await _contact(async_connection, 1)
        await _journal(async_connection, 1, 1, created_at=CUTOFF + timedelta(seconds=1))
        await _journal(async_connection, 2, 1, created_at=CUTOFF - timedelta(seconds=1))
        await _history(
            async_connection,
            entity_type="contact",
            entity_id=1,
            created_at=CUTOFF + timedelta(seconds=1),
        )
        await _history(
            async_connection,
            entity_type="contact",
            entity_id=1,
            created_at=CUTOFF - timedelta(seconds=1),
        )

        signals = await repository.for_contacts([1], now=NOW)

        assert signals[1].journal_count_30d == 1
        assert signals[1].activity_count_30d == 1

    async def test_a_row_exactly_on_the_cutoff_counts(
        self,
        async_connection: AsyncConnection,
        repository: SqlContactImportanceRepository,
    ) -> None:
        """The comparison is inclusive, as the search ranking has always had it."""
        await _contact(async_connection, 1)
        await _journal(async_connection, 1, 1, created_at=CUTOFF)
        await _history(
            async_connection, entity_type="contact", entity_id=1, created_at=CUTOFF
        )

        signals = await repository.for_contacts([1], now=NOW)

        assert signals[1].journal_count_30d == 1
        assert signals[1].activity_count_30d == 1


class TestActivity:
    """What counts as activity on a contact."""

    async def test_changes_to_the_contacts_children_count_as_activity(
        self,
        async_connection: AsyncConnection,
        repository: SqlContactImportanceRepository,
    ) -> None:
        """Editing a phone number is activity on the contact, not on nothing.

        The four child types are what the contact history read already treats as
        the contact's own, and the search ranking has counted them since it
        gained the signal.
        """
        await _contact(async_connection, 1)
        await async_connection.execute(
            text("""
                INSERT INTO contact_methods
                    (id, contact_id, method_type, value, created_at, updated_at)
                VALUES (11, 1, 'email', 'someone@example.com', :now, :now)
            """),
            {"now": NOW},
        )
        await async_connection.execute(
            text("""
                INSERT INTO contact_addresses
                    (id, contact_id, street_line_1, country_code, created_at, updated_at)
                VALUES (12, 1, '1 Test Street', 'AU', :now, :now)
            """),
            {"now": NOW},
        )
        await async_connection.execute(
            text("""
                INSERT INTO contact_notes (id, contact_id, content, created_at, updated_at)
                VALUES (13, 1, 'A note', :now, :now)
            """),
            {"now": NOW},
        )
        await async_connection.execute(
            text("""
                INSERT INTO tags (id, name, created_at, updated_at)
                VALUES (14, 'friends', :now, :now)
            """),
            {"now": NOW},
        )
        await async_connection.execute(
            text("""
                INSERT INTO contact_tags (contact_id, tag_id, created_at)
                VALUES (1, 14, :now)
            """),
            {"now": NOW},
        )
        for entity_type, entity_id in (
            ("contact", 1),
            ("contact_method", 11),
            ("contact_address", 12),
            ("contact_note", 13),
            ("contact_tag", 14),
        ):
            await _history(
                async_connection,
                entity_type=entity_type,
                entity_id=entity_id,
                created_at=NOW - timedelta(days=1),
            )

        signals = await repository.for_contacts([1], now=NOW)

        assert signals[1].activity_count_30d == 5

    async def test_another_contacts_activity_is_not_counted(
        self,
        async_connection: AsyncConnection,
        repository: SqlContactImportanceRepository,
    ) -> None:
        """Signals are per contact, however busy the neighbouring row is."""
        await _contact(async_connection, 1)
        await _contact(async_connection, 2)
        await _journal(async_connection, 1, 2, created_at=NOW - timedelta(days=1))
        await _history(
            async_connection,
            entity_type="contact",
            entity_id=2,
            created_at=NOW - timedelta(days=1),
        )

        signals = await repository.for_contacts([1, 2], now=NOW)

        assert signals[1].journal_count_30d == 0
        assert signals[1].activity_count_30d == 0
        assert signals[2].journal_count_30d == 1
        assert signals[2].activity_count_30d == 1

    async def test_a_colliding_id_on_another_contacts_child_is_not_counted(
        self,
        async_connection: AsyncConnection,
        repository: SqlContactImportanceRepository,
    ) -> None:
        """The entity type has to name the table the id was drawn from.

        The four child tables have independent id sequences, so a note and a
        method sharing an id is ordinary rather than exotic. Matching the type
        set and the id set independently — which the predicate did until
        #1396 — counts contact 2's note edit against contact 1, because
        contact 1 owns *a* child row numbered 5.
        """
        await _contact(async_connection, 1)
        await _contact(async_connection, 2)
        await _contact_method(async_connection, 5, 1)
        await _contact_note(async_connection, 5, 2)
        await _history(
            async_connection,
            entity_type="contact_note",
            entity_id=5,
            created_at=NOW - timedelta(days=1),
        )

        signals = await repository.for_contacts([1, 2], now=NOW)

        assert signals[1].activity_count_30d == 0
        assert signals[2].activity_count_30d == 1

    async def test_a_colliding_id_on_another_contact_does_not_move_last_activity(
        self,
        async_connection: AsyncConnection,
        repository: SqlContactImportanceRepository,
    ) -> None:
        """The same mismatch inflated the instant as well as the count.

        ``last_activity_at`` is the maximum over the rows the predicate
        matches, so a foreign row it wrongly matched made a long-untouched
        contact look freshly active.
        """
        await _contact(async_connection, 1, updated_at=NOW - timedelta(days=200))
        await _contact(async_connection, 2)
        await _contact_method(async_connection, 5, 1)
        await _contact_note(async_connection, 5, 2)
        await _history(
            async_connection,
            entity_type="contact_note",
            entity_id=5,
            created_at=NOW - timedelta(days=1),
        )

        signals = await repository.for_contacts([1], now=NOW)

        assert signals[1].last_activity_at == NOW - timedelta(days=200)

    async def test_a_type_naming_a_table_the_contact_has_no_such_row_in_is_not_counted(
        self,
        async_connection: AsyncConnection,
        repository: SqlContactImportanceRepository,
    ) -> None:
        """One contact's own ids do not vouch for each other either.

        Contact 1 owns method 11 and no tag at all, so a ``contact_tag`` row
        numbered 11 is some other contact's tag — or none — and is activity on
        neither.
        """
        await _contact(async_connection, 1)
        await _contact_method(async_connection, 11, 1)
        await _history(
            async_connection,
            entity_type="contact_tag",
            entity_id=11,
            created_at=NOW - timedelta(days=1),
        )

        signals = await repository.for_contacts([1], now=NOW)

        assert signals[1].activity_count_30d == 0


class TestLastActivity:
    """The freshest moment anything about the contact moved."""

    async def test_a_contact_with_nothing_attached_falls_back_to_its_own_row(
        self,
        async_connection: AsyncConnection,
        repository: SqlContactImportanceRepository,
    ) -> None:
        """No journals and no history is zeros, not an absent contact."""
        await _contact(async_connection, 1, updated_at=NOW - timedelta(days=200))

        signals = await repository.for_contacts([1], now=NOW)

        assert signals[1].contact_id == 1
        assert signals[1].is_favourite is False
        assert signals[1].journal_count_30d == 0
        assert signals[1].activity_count_30d == 0
        assert signals[1].last_activity_at == NOW - timedelta(days=200)

    async def test_a_newer_journal_moves_it(
        self,
        async_connection: AsyncConnection,
        repository: SqlContactImportanceRepository,
    ) -> None:
        """It is the maximum across all three sources, not the contact's own row."""
        await _contact(async_connection, 1, updated_at=NOW - timedelta(days=10))
        await _journal(async_connection, 1, 1, created_at=NOW - timedelta(days=2))
        await _history(
            async_connection,
            entity_type="contact",
            entity_id=1,
            created_at=NOW - timedelta(days=5),
        )

        signals = await repository.for_contacts([1], now=NOW)

        assert signals[1].last_activity_at == NOW - timedelta(days=2)

    async def test_a_newer_history_row_moves_it(
        self,
        async_connection: AsyncConnection,
        repository: SqlContactImportanceRepository,
    ) -> None:
        """The history source wins when it is the freshest of the three."""
        await _contact(async_connection, 1, updated_at=NOW - timedelta(days=10))
        await _journal(async_connection, 1, 1, created_at=NOW - timedelta(days=5))
        await _history(
            async_connection,
            entity_type="contact",
            entity_id=1,
            created_at=NOW - timedelta(days=1),
        )

        signals = await repository.for_contacts([1], now=NOW)

        assert signals[1].last_activity_at == NOW - timedelta(days=1)

    async def test_a_row_outside_the_window_still_moves_it(
        self,
        async_connection: AsyncConnection,
        repository: SqlContactImportanceRepository,
    ) -> None:
        """Recency is not the window: a year-old journal is still the last thing."""
        await _contact(async_connection, 1, updated_at=NOW - timedelta(days=400))
        await _journal(async_connection, 1, 1, created_at=NOW - timedelta(days=300))

        signals = await repository.for_contacts([1], now=NOW)

        assert signals[1].journal_count_30d == 0
        assert signals[1].last_activity_at == NOW - timedelta(days=300)


class TestTheBatch:
    """Reading many contacts at once, which is what the dashboard does."""

    async def test_a_batch_is_answered_in_one_statement(
        self,
        async_connection: AsyncConnection,
        repository: SqlContactImportanceRepository,
    ) -> None:
        """The dashboard ranks a whole window of contacts; per-contact would be an N+1."""
        for contact_id in (1, 2, 3):
            await _contact(async_connection, contact_id)
            await _journal(
                async_connection,
                contact_id,
                contact_id,
                created_at=NOW - timedelta(days=1),
            )

        with recorded_statements(async_connection) as statements:
            signals = await repository.for_contacts([1, 2, 3], now=NOW)

        assert len(statements) == 1
        assert sorted(signals) == [1, 2, 3]
        assert all(signals[contact_id].journal_count_30d == 1 for contact_id in signals)

    async def test_unknown_ids_are_absent_rather_than_empty_signals(
        self,
        async_connection: AsyncConnection,
        repository: SqlContactImportanceRepository,
    ) -> None:
        """A deleted contact has no signals to report, which is not the same as zeros."""
        await _contact(async_connection, 1)

        signals = await repository.for_contacts([1, 999], now=NOW)

        assert sorted(signals) == [1]

    async def test_no_ids_is_answered_without_asking_the_database(
        self,
        async_connection: AsyncConnection,
        repository: SqlContactImportanceRepository,
    ) -> None:
        """An empty window is the common case and deserves no round trip."""
        with recorded_statements(async_connection) as statements:
            signals = await repository.for_contacts([], now=NOW)

        assert signals == {}
        assert statements == []

    async def test_favourite_is_read_from_the_contact(
        self,
        async_connection: AsyncConnection,
        repository: SqlContactImportanceRepository,
    ) -> None:
        """The strongest signal is the one the user set by hand."""
        await _contact(async_connection, 1, is_favourite=True)
        await _contact(async_connection, 2, is_favourite=False)

        signals = await repository.for_contacts([1, 2], now=NOW)

        assert signals[1].is_favourite is True
        assert signals[2].is_favourite is False


class TestIndependenceFromSearch:
    """The dashboard must be able to read this with MeiliSearch down."""

    async def test_the_read_works_while_meilisearch_is_unavailable(
        self,
        async_connection: AsyncConnection,
        repository: SqlContactImportanceRepository,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Extraction was chosen over querying the index for exactly this reason.

        Reading the signals back out of the search index would have made the
        dashboard's upcoming-dates section fail whenever search was down. This
        read touches PostgreSQL only, and a client factory that raises on sight
        proves it rather than asserting it in a comment.
        """

        def unavailable() -> None:
            raise RuntimeError("MeiliSearch is unavailable")

        monkeypatch.setattr(
            "app.infrastructure.search.meilisearch_client.get_meilisearch_client",
            unavailable,
        )
        await _contact(async_connection, 1, is_favourite=True)
        await _journal(async_connection, 1, 1, created_at=NOW - timedelta(days=1))

        signals = await repository.for_contacts([1], now=NOW)

        assert signals[1].is_favourite is True
        assert signals[1].journal_count_30d == 1
