"""Integration tests for the contact update precondition (optimistic concurrency).

See the journal counterpart for why a concurrent writer is simulated by nudging
``updated_at`` rather than by performing a second real write.
"""

import pytest
from core_shared.etag import resource_etag
from core_shared.exceptions import PreconditionFailedError
from core_shared.models.contacts.entities import Contact
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import (
    SqlContactEventPublisher,
    SqlContactFieldHistoryRepository,
    SqlContactRepository,
    SqlTagRepository,
)
from app.core.contacts.services import ContactService
from tests.integration.contact_seeding import TEST_USER_ID


async def _simulate_concurrent_write(
    connection: AsyncConnection, contact_id: int
) -> None:
    """Move the row's ``updated_at`` on, as another writer's commit would."""
    await connection.execute(
        text(
            "UPDATE contacts SET updated_at = updated_at + interval '1 second' "
            "WHERE id = :contact_id"
        ),
        {"contact_id": contact_id},
    )


@pytest.mark.integration
class TestContactUpdatePrecondition:
    """``ContactService.update_contact`` under an ``expected_etags`` precondition."""

    @pytest.fixture
    def contact_repo(self, clean_database: AsyncConnection):
        return SqlContactRepository(clean_database)

    @pytest.fixture
    def contact_service(self, contact_repo, clean_database: AsyncConnection):
        from app.core.contacts.services import (
            AddressValidationService,
            ContactHistoryService,
            ContactValidationService,
            TagHierarchyService,
            TagService,
        )

        tag_repo = SqlTagRepository(clean_database)
        history_repo = SqlContactFieldHistoryRepository(clean_database)
        event_publisher = SqlContactEventPublisher(clean_database)
        tag_hierarchy_service = TagHierarchyService(tag_repo)
        return ContactService(
            contact_repo=contact_repo,
            tag_repo=tag_repo,
            history_repo=history_repo,
            event_publisher=event_publisher,
            address_validation_service=AddressValidationService(),
            contact_validation_service=ContactValidationService(contact_repo),
            history_service=ContactHistoryService(history_repo),
            tag_hierarchy_service=tag_hierarchy_service,
            tag_service=TagService(
                tag_repo=tag_repo,
                tag_hierarchy_service=tag_hierarchy_service,
                event_publisher=event_publisher,
            ),
        )

    @pytest.mark.asyncio
    async def test_matching_tag_permits_the_write(
        self, contact_service, clean_database: AsyncConnection
    ):
        saved = await contact_service.create_contact(
            Contact(user_id=TEST_USER_ID, first_name="Ada", last_name="Lovelace"),
            clean_database,
        )
        etag = resource_etag("contacts", saved.id, saved.updated_at)

        saved.first_name = "Augusta"
        result = await contact_service.update_contact(
            saved, clean_database, expected_etags=[etag]
        )

        assert result.first_name == "Augusta"

    @pytest.mark.asyncio
    async def test_stale_tag_refuses_the_write(
        self, contact_service, contact_repo, clean_database: AsyncConnection
    ):
        saved = await contact_service.create_contact(
            Contact(user_id=TEST_USER_ID, first_name="Ada", last_name="Lovelace"),
            clean_database,
        )
        stale_etag = resource_etag("contacts", saved.id, saved.updated_at)
        await _simulate_concurrent_write(clean_database, saved.id)

        saved.first_name = "Augusta"
        with pytest.raises(PreconditionFailedError) as exc_info:
            await contact_service.update_contact(
                saved, clean_database, expected_etags=[stale_etag]
            )

        assert exc_info.value.status_code == 412
        persisted = await contact_repo.find_by_id(saved.id)
        assert persisted.first_name == "Ada"

    @pytest.mark.asyncio
    async def test_refusal_happens_before_any_related_write(
        self, contact_service, clean_database: AsyncConnection
    ):
        """A refused update must not leave the tags it would have resolved.

        ``update_contact`` find-or-creates tag rows before touching the contact
        itself, so the precondition has to be checked ahead of that or a
        conflict would still have written something.
        """
        saved = await contact_service.create_contact(
            Contact(user_id=TEST_USER_ID, first_name="Ada", last_name="Lovelace"),
            clean_database,
        )
        stale_etag = resource_etag("contacts", saved.id, saved.updated_at)
        await _simulate_concurrent_write(clean_database, saved.id)

        with pytest.raises(PreconditionFailedError):
            await contact_service.update_contact(
                saved,
                clean_database,
                expected_etags=[stale_etag],
                tag_names=["Mathematician"],
            )

        assert (
            await SqlTagRepository(clean_database).find_by_name("Mathematician") is None
        )

    @pytest.mark.asyncio
    async def test_no_precondition_writes_as_before(
        self, contact_service, clean_database: AsyncConnection
    ):
        """The feature is opt-in: today's callers send nothing and are unaffected."""
        saved = await contact_service.create_contact(
            Contact(user_id=TEST_USER_ID, first_name="Ada", last_name="Lovelace"),
            clean_database,
        )
        await _simulate_concurrent_write(clean_database, saved.id)

        saved.first_name = "Augusta"
        result = await contact_service.update_contact(saved, clean_database)

        assert result.first_name == "Augusta"
