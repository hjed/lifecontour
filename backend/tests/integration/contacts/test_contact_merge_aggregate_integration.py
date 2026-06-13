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
    SqlContactFieldHistoryRepository,
    SqlContactRelationshipRepository,
    SqlContactRepository,
)
from app.core.contacts.models.repositories import (
    ContactEventPublisher,
    DomainEventProtocol,
)
from app.core.contacts.services.contact_history_service import ContactHistoryService
from app.core.contacts.services.contact_merge_service import ContactMergeService
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)


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
async def merge_service(
    async_connection: AsyncConnection,
    contact_repo: SqlContactRepository,
    event_publisher: RecordingEventPublisher,
) -> ContactMergeService:
    history_service = ContactHistoryService(
        SqlContactFieldHistoryRepository(async_connection)
    )
    return ContactMergeService(
        contact_repo=contact_repo,
        relationship_repo=SqlContactRelationshipRepository(async_connection),
        journal_relationship_repo=SqlJournalContactRelationshipRepository(
            async_connection
        ),
        history_service=history_service,
        event_publisher=event_publisher,
    )


def _id(contact: Contact) -> int:
    assert contact.id is not None, "Contact must have an ID after save"
    return contact.id


async def _make_contact(repo: SqlContactRepository, first_name: str, **scalars) -> int:
    return _id(await repo.save(Contact(first_name=first_name, **scalars)))


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
    repo: SqlContactRepository, contact_id: int, value: str, *, is_primary: bool = False
) -> None:
    await repo.add_method(
        contact_id,
        ContactMethod(
            method_type=MethodType.PHONE,
            value=value,
            contact_id=contact_id,
            is_primary=is_primary,
        ),
    )


async def _add_address(
    repo: SqlContactRepository,
    contact_id: int,
    street: str,
    *,
    is_primary: bool,
) -> None:
    await repo.add_address(
        contact_id,
        ContactAddress(
            street_line_1=street,
            country_code="AU",
            contact_id=contact_id,
            is_primary=is_primary,
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
            survivor_id, source_id, transaction=async_connection
        )

        survivor = await contact_repo.find_by_id(survivor_id)
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
            survivor_id, source_id, transaction=async_connection
        )

        assert await contact_repo.find_by_id(source_id) is None
        assert await contact_repo.find_by_id(survivor_id) is not None

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
            survivor_id, source_id, transaction=async_connection
        )

        survivor = await contact_repo.find_by_id(survivor_id)
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
            survivor_id, source_id, transaction=async_connection
        )

        survivor = await contact_repo.find_by_id(survivor_id)
        assert survivor is not None
        phones = [
            m for m in (survivor.methods or []) if m.method_type == MethodType.PHONE
        ]
        assert [m.value for m in phones] == ["+61400000001"]

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
            survivor_id, source_id, transaction=async_connection
        )

        survivor = await contact_repo.find_by_id(survivor_id)
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
            survivor_id, source_id, transaction=async_connection
        )

        survivor = await contact_repo.find_by_id(survivor_id)
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
            survivor_id, source_id, transaction=async_connection
        )

        survivor = await contact_repo.find_by_id(survivor_id)
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
            survivor_id, source_id, transaction=async_connection
        )

        survivor = await contact_repo.find_by_id(survivor_id)
        assert survivor is not None
        assert survivor.first_name == "Survivor"
        assert survivor.last_name == "Keep"  # survivor wins on conflict
        assert survivor.company == "Acme"  # source fills the survivor's gap

    @pytest.mark.asyncio
    async def test_merge_records_merged_from_history_row(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
    ) -> None:
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection
        )

        result = await async_connection.execute(
            text(
                """
                SELECT old_value FROM field_history
                WHERE entity_type = 'contact'
                AND entity_id = :survivor_id
                AND field_name = 'merged_from'
                """
            ),
            {"survivor_id": survivor_id},
        )
        rows = result.fetchall()
        assert len(rows) == 1
        assert rows[0].old_value == str(source_id)

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
            survivor_id, source_id, transaction=async_connection
        )

        refresh_events = [
            e
            for e in event_publisher.events
            if e.event_type == "ContactSummaryRefreshRequested"
        ]
        assert len(refresh_events) == 1
        assert refresh_events[0].aggregate_id == survivor_id
