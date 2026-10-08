"""Integration tests for the full-aggregate contact merge (ITER13-001 Phase 2).

Drives ``ContactMergeService.merge_contacts`` against a real database to verify
the engine produces a correct, deduplicated survivor under the default
survivor-wins / prefer-non-empty policy: sub-entities carry over and dedupe, the
constraint hotspots resolve without violation, the source is deleted, the merge
``field_history`` row is written, and a survivor summary refresh is requested.

Note on email uniqueness: ``ix_contact_methods_email_unique`` makes email values
unique *system-wide*, so two contacts can never pre-hold the same email. The
"colliding email" case is therefore exercised as (a) distinct emails coexisting
on the survivor after re-point and (b) the primary-email collision being demoted
(``ix_contact_methods_primary_unique``). Exact-value duplicate collapse is
covered via phone, which has no global-uniqueness constraint.
"""

from collections.abc import Sequence

import pytest
import pytest_asyncio
from core_shared.models.contacts.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    ImportantDate,
    MethodType,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import (
    SqlContactRelationshipRepository,
    SqlContactRepository,
)
from app.core.contacts.models.repositories import (
    ContactEventPublisher,
    DomainEventProtocol,
)
from app.core.contacts.services.contact_merge_service import ContactMergeService
from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.models import FieldHistoryEntry
from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.tasks.adapters.sql.task_contact_repository import (
    SqlTaskContactRepository,
)
from app.core.tasks.services.task_contact_merge_service import (
    TaskContactMergeService,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.contact_seeding import TEST_USER_ID


class RecordingEventPublisher(ContactEventPublisher):
    """A ``ContactEventPublisher`` that records published events for assertions."""

    def __init__(self) -> None:
        self.events: list[DomainEventProtocol] = []

    async def publish(self, event: DomainEventProtocol) -> None:
        self.events.append(event)

    async def publish_batch(self, events: Sequence[DomainEventProtocol]) -> None:
        self.events.extend(events)


@pytest_asyncio.fixture
async def contact_repo(async_connection: AsyncConnection) -> SqlContactRepository:
    return SqlContactRepository(async_connection)


@pytest_asyncio.fixture
async def event_publisher() -> RecordingEventPublisher:
    return RecordingEventPublisher()


@pytest_asyncio.fixture
async def history_repo(
    async_connection: AsyncConnection,
) -> SqlFieldHistoryRepository:
    return SqlFieldHistoryRepository(async_connection)


@pytest_asyncio.fixture
async def merge_service(
    async_connection: AsyncConnection,
    contact_repo: SqlContactRepository,
    event_publisher: RecordingEventPublisher,
    history_repo: SqlFieldHistoryRepository,
) -> ContactMergeService:
    return ContactMergeService(
        contact_repo=contact_repo,
        relationship_repo=SqlContactRelationshipRepository(async_connection),
        journal_relationship_repo=SqlJournalContactRelationshipRepository(
            async_connection
        ),
        event_publisher=event_publisher,
        history_repo=history_repo,
        sync_metadata_repo=SyncMetadataRepository(async_connection),
        task_merge_service=TaskContactMergeService(
            task_contact_repo=SqlTaskContactRepository(async_connection),
            event_publisher=OutboxEventPublisher(async_connection),
        ),
    )


def _id(contact: Contact) -> int:
    assert contact.id is not None, "Contact must have an ID after save"
    return contact.id


async def _make_contact(repo: SqlContactRepository, first_name: str, **scalars) -> int:
    return _id(
        await repo.save(Contact(first_name=first_name, user_id=TEST_USER_ID, **scalars))
    )


async def _add_email(
    repo: SqlContactRepository, contact_id: int, value: str, *, is_primary: bool
) -> None:
    await repo.add_method(
        contact_id,
        ContactMethod(
            method_type=MethodType.EMAIL,
            value=value,
            contact_id=contact_id,
            is_primary=is_primary,
        ),
    )


async def _add_phone(
    repo: SqlContactRepository,
    contact_id: int,
    value: str,
    *,
    is_primary: bool = False,
    is_archived: bool = False,
) -> None:
    await repo.add_method(
        contact_id,
        ContactMethod(
            method_type=MethodType.PHONE,
            value=value,
            contact_id=contact_id,
            is_primary=is_primary,
            is_archived=is_archived,
        ),
    )


async def _add_address(
    repo: SqlContactRepository,
    contact_id: int,
    street: str,
    *,
    is_primary: bool,
    is_archived: bool = False,
) -> None:
    await repo.add_address(
        contact_id,
        ContactAddress(
            street_line_1=street,
            country_code="AU",
            contact_id=contact_id,
            is_primary=is_primary,
            is_archived=is_archived,
        ),
    )


async def _add_note(repo: SqlContactRepository, contact_id: int, content: str) -> None:
    await repo.add_note(contact_id, ContactNote(content=content, contact_id=contact_id))


async def _add_birthday(
    repo: SqlContactRepository, contact_id: int, *, month: int, day: int
) -> None:
    await repo.add_important_date(
        contact_id,
        ImportantDate(
            contact_id=contact_id,
            date_type=ImportantDateType.BIRTHDAY,
            precision=DatePrecision.DAY_MONTH,
            month=month,
            day=day,
        ),
    )


async def _make_tag(connection: AsyncConnection, name: str) -> int:
    result = await connection.execute(
        text("INSERT INTO tags (name) VALUES (:name) RETURNING id"),
        {"name": name},
    )
    tag_id = result.scalar()
    assert tag_id is not None
    return int(tag_id)


@pytest.mark.integration
class TestContactMergeAggregateIntegration:
    """Full-aggregate merge against a real database."""

    @pytest.mark.asyncio
    async def test_full_aggregate_unions_non_duplicate_sub_entities(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
    ) -> None:
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")

        await _add_email(
            contact_repo, survivor_id, "survivor@example.com", is_primary=True
        )
        await _add_email(contact_repo, source_id, "source@example.com", is_primary=True)
        await _add_address(contact_repo, survivor_id, "1 Survivor St", is_primary=True)
        await _add_address(contact_repo, source_id, "2 Source Ave", is_primary=True)
        await _add_note(contact_repo, survivor_id, "survivor note")
        await _add_note(contact_repo, source_id, "source note")
        tag_a = await _make_tag(async_connection, "alpha")
        tag_b = await _make_tag(async_connection, "beta")
        await contact_repo.assign_tag(survivor_id, tag_a)
        await contact_repo.assign_tag(source_id, tag_b)

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        survivor = await contact_repo.find_by_id(survivor_id, user_id=TEST_USER_ID)
        assert survivor is not None
        assert {m.value for m in (survivor.methods or [])} == {
            "survivor@example.com",
            "source@example.com",
        }
        assert {a.street_line_1 for a in (survivor.addresses or [])} == {
            "1 Survivor St",
            "2 Source Ave",
        }
        assert {n.content for n in (survivor.notes or [])} == {
            "survivor note",
            "source note",
        }
        assert {t.id for t in (survivor.tags or [])} == {tag_a, tag_b}

    @pytest.mark.asyncio
    async def test_source_contact_is_deleted(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
    ) -> None:
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        assert await contact_repo.find_by_id(source_id, user_id=TEST_USER_ID) is None
        assert (
            await contact_repo.find_by_id(survivor_id, user_id=TEST_USER_ID) is not None
        )

    @pytest.mark.asyncio
    async def test_duplicate_primary_email_demoted_and_coexists(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
    ) -> None:
        """Both contacts have a primary email; after merge both emails live on the
        survivor but exactly one stays primary (survivor's)."""
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        await _add_email(contact_repo, survivor_id, "keep@example.com", is_primary=True)
        await _add_email(contact_repo, source_id, "other@example.com", is_primary=True)

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        survivor = await contact_repo.find_by_id(survivor_id, user_id=TEST_USER_ID)
        assert survivor is not None
        emails = [
            m for m in (survivor.methods or []) if m.method_type == MethodType.EMAIL
        ]
        assert {m.value for m in emails} == {"keep@example.com", "other@example.com"}
        primaries = [m for m in emails if m.is_primary]
        assert len(primaries) == 1
        assert primaries[0].value == "keep@example.com"

    @pytest.mark.asyncio
    async def test_exact_duplicate_phone_collapses(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
    ) -> None:
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        await _add_phone(contact_repo, survivor_id, "+61400000001")
        await _add_phone(contact_repo, source_id, "+61400000001")

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        survivor = await contact_repo.find_by_id(survivor_id, user_id=TEST_USER_ID)
        assert survivor is not None
        phones = [
            m for m in (survivor.methods or []) if m.method_type == MethodType.PHONE
        ]
        assert [m.value for m in phones] == ["+61400000001"]

    @pytest.mark.asyncio
    async def test_duplicate_phone_stays_active_if_either_holds_it_active(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
    ) -> None:
        """The survivor archived the number, the source still uses it: in use wins."""
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        await _add_phone(contact_repo, survivor_id, "+61400000001", is_archived=True)
        await _add_phone(contact_repo, source_id, "+61400000001")

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        survivor = await contact_repo.find_by_id(survivor_id, user_id=TEST_USER_ID)
        assert survivor is not None
        assert [(m.value, m.is_archived) for m in survivor.methods or []] == [
            ("+61400000001", False)
        ]

    @pytest.mark.asyncio
    async def test_duplicate_address_stays_active_if_either_holds_it_active(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
    ) -> None:
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        await _add_address(
            contact_repo, survivor_id, "1 Shared St", is_primary=False, is_archived=True
        )
        await _add_address(contact_repo, source_id, "1 Shared St", is_primary=False)

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        survivor = await contact_repo.find_by_id(survivor_id, user_id=TEST_USER_ID)
        assert survivor is not None
        assert [(a.street_line_1, a.is_archived) for a in survivor.addresses or []] == [
            ("1 Shared St", False)
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("survivor_archived", [False, True])
    async def test_collapsed_phone_keeps_the_sources_primary(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
        survivor_archived: bool,
    ) -> None:
        """The survivor holds the number with no primary phone; the source's copy
        is its primary. The copies collapse into the survivor's row, which must
        keep that primary rather than lose it with the source's row."""
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        await _add_phone(
            contact_repo, survivor_id, "+61400000001", is_archived=survivor_archived
        )
        await _add_phone(contact_repo, source_id, "+61400000001", is_primary=True)

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        survivor = await contact_repo.find_by_id(survivor_id, user_id=TEST_USER_ID)
        assert survivor is not None
        assert [
            (m.value, m.is_primary, m.is_archived) for m in survivor.methods or []
        ] == [("+61400000001", True, False)]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("survivor_archived", [False, True])
    async def test_collapsed_address_keeps_the_sources_primary(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
        survivor_archived: bool,
    ) -> None:
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        await _add_address(
            contact_repo,
            survivor_id,
            "1 Shared St",
            is_primary=False,
            is_archived=survivor_archived,
        )
        await _add_address(contact_repo, source_id, "1 Shared St", is_primary=True)

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        survivor = await contact_repo.find_by_id(survivor_id, user_id=TEST_USER_ID)
        assert survivor is not None
        assert [
            (a.street_line_1, a.is_primary, a.is_archived)
            for a in survivor.addresses or []
        ] == [("1 Shared St", True, False)]

    @pytest.mark.asyncio
    async def test_survivors_twin_copies_get_one_primary(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
    ) -> None:
        """Two survivor copies of the source's primary: only one takes it."""
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        await _add_phone(contact_repo, survivor_id, "+61400000001")
        await _add_phone(contact_repo, survivor_id, "+61400000001", is_archived=True)
        await _add_phone(contact_repo, source_id, "+61400000001", is_primary=True)

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        survivor = await contact_repo.find_by_id(survivor_id, user_id=TEST_USER_ID)
        assert survivor is not None
        assert sum(m.is_primary for m in survivor.methods or []) == 1

    @pytest.mark.asyncio
    async def test_collapsed_phone_leaves_the_survivors_primary_alone(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
    ) -> None:
        """With a primary phone of its own, the survivor's primary wins."""
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        await _add_phone(contact_repo, survivor_id, "+61400000009", is_primary=True)
        await _add_phone(contact_repo, survivor_id, "+61400000001")
        await _add_phone(contact_repo, source_id, "+61400000001", is_primary=True)

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        survivor = await contact_repo.find_by_id(survivor_id, user_id=TEST_USER_ID)
        assert survivor is not None
        assert {(m.value, m.is_primary) for m in survivor.methods or []} == {
            ("+61400000009", True),
            ("+61400000001", False),
        }

    @pytest.mark.asyncio
    async def test_duplicate_primary_address_demoted(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
    ) -> None:
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        await _add_address(contact_repo, survivor_id, "1 Keep St", is_primary=True)
        await _add_address(contact_repo, source_id, "2 Other Rd", is_primary=True)

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        survivor = await contact_repo.find_by_id(survivor_id, user_id=TEST_USER_ID)
        assert survivor is not None
        addresses = survivor.addresses or []
        assert len(addresses) == 2
        primaries = [a for a in addresses if a.is_primary]
        assert len(primaries) == 1
        assert primaries[0].street_line_1 == "1 Keep St"

    @pytest.mark.asyncio
    async def test_duplicate_tag_collapses_to_union(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
    ) -> None:
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        shared = await _make_tag(async_connection, "shared")
        source_only = await _make_tag(async_connection, "source-only")
        await contact_repo.assign_tag(survivor_id, shared)
        await contact_repo.assign_tag(source_id, shared)
        await contact_repo.assign_tag(source_id, source_only)

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        survivor = await contact_repo.find_by_id(survivor_id, user_id=TEST_USER_ID)
        assert survivor is not None
        assert {t.id for t in (survivor.tags or [])} == {shared, source_only}

    @pytest.mark.asyncio
    async def test_duplicate_birthday_keeps_survivor(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
    ) -> None:
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        await _add_birthday(contact_repo, survivor_id, month=1, day=1)
        await _add_birthday(contact_repo, source_id, month=2, day=2)

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        survivor = await contact_repo.find_by_id(survivor_id, user_id=TEST_USER_ID)
        assert survivor is not None
        birthdays = [
            d
            for d in (survivor.important_dates or [])
            if d.date_type == ImportantDateType.BIRTHDAY
        ]
        assert len(birthdays) == 1
        assert (birthdays[0].month, birthdays[0].day) == (1, 1)

    @pytest.mark.asyncio
    async def test_scalar_prefer_non_empty_fills_survivor_gaps(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
    ) -> None:
        survivor_id = await _make_contact(
            contact_repo, "Survivor", last_name="Keep", company=None
        )
        source_id = await _make_contact(
            contact_repo, "Source", last_name="Drop", company="Acme"
        )

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        survivor = await contact_repo.find_by_id(survivor_id, user_id=TEST_USER_ID)
        assert survivor is not None
        assert survivor.first_name == "Survivor"
        assert survivor.last_name == "Keep"  # survivor wins on conflict
        assert survivor.company == "Acme"  # source fills the survivor's gap

    @pytest.mark.asyncio
    async def test_merge_publishes_merged_from_history_event(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
        event_publisher: RecordingEventPublisher,
    ) -> None:
        """ITER12-003 Phase 2: the merged_from audit row is now derived from a
        published ContactUpdated event (the history projection writes it), not a
        synchronous history write."""
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        merged_events = [
            e for e in event_publisher.events if e.event_type == "ContactUpdated"
        ]
        assert len(merged_events) == 1
        event = merged_events[0]
        assert event.aggregate_id == survivor_id
        changed_fields = event.event_data["changed_fields"]
        assert changed_fields["merged_from"] == (source_id, survivor_id)

    @pytest.mark.asyncio
    async def test_merge_repoints_source_history_onto_survivor(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
        history_repo: SqlFieldHistoryRepository,
    ) -> None:
        """The source's pre-merge top-level history is carried onto the survivor so
        the unified record's aggregate history is complete."""
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        # A pre-merge change recorded against the source contact.
        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="contact",
                entity_id=source_id,
                field_name="first_name",
                old_value="Source",
                new_value="Sourced",
                event_id="evt-premerge",
            )
        )

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        aggregate = await history_repo.get_history_for_aggregate(
            "contact", survivor_id, limit=50, offset=0
        )
        moved = [
            e
            for e in aggregate
            if e.field_name == "first_name" and e.event_id == "evt-premerge"
        ]
        assert len(moved) == 1
        assert moved[0].entity_id == survivor_id
        # No orphaned top-level rows remain for the deleted source.
        source_rows = await history_repo.get_entity_history("contact", source_id)
        assert source_rows == []

    @pytest.mark.asyncio
    async def test_merge_requests_summary_refresh_for_survivor(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
        event_publisher: RecordingEventPublisher,
    ) -> None:
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        refresh_events = [
            e
            for e in event_publisher.events
            if e.event_type == "ContactSummaryRefreshRequested"
        ]
        assert len(refresh_events) == 1
        assert refresh_events[0].aggregate_id == survivor_id
