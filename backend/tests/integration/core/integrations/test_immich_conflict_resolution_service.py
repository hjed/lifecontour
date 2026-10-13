"""Integration tests for ImmichConflictResolutionService.

Resolving a conflict links an Immich person to one of the user's contacts --
an existing one, or one created from the person's name -- and records that
link in ``sync_metadata``. Every write commits together or not at all.
"""

import pytest
from core_shared.models.contacts.value_objects import Provenance
from core_shared.repositories.pending_entity_mapping_repository import (
    PendingEntityMappingRepository,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.integrations.immich.conflict_resolution_service import (
    ConflictResolutionAction,
    ImmichConflictContactRequiredError,
    ImmichConflictNotFoundError,
    ImmichConflictResolutionService,
)
from tests.integration.contact_seeding import (
    OTHER_USER_ID,
    TEST_USER_ID,
    seed_contact,
)
from tests.integration.contacts.contact_service_harness import (
    RecordingEventPublisher,
    build_contact_service,
)

PERSON_ID = "person-abc"


class FailingSyncMetadataRepository(SyncMetadataRepository):
    """Fails the final write, to prove the earlier ones roll back with it."""

    async def upsert_contact_link(
        self,
        contact_id: int,
        *,
        user_id: str,
        external_system: str,
        external_entity_type: str,
        external_entity_id: str,
    ) -> None:
        raise RuntimeError("link store unavailable")


def _service(
    connection: AsyncConnection,
    sync_metadata_repo: SyncMetadataRepository | None = None,
) -> ImmichConflictResolutionService:
    return ImmichConflictResolutionService(
        conflict_repo=PendingEntityMappingRepository(connection),
        contact_repo=SqlContactRepository(connection),
        sync_metadata_repo=sync_metadata_repo or SyncMetadataRepository(connection),
        contact_service=build_contact_service(connection, RecordingEventPublisher()),
    )


@pytest.fixture
def service(async_connection: AsyncConnection) -> ImmichConflictResolutionService:
    return _service(async_connection)


async def _seed_conflict(
    connection: AsyncConnection,
    *,
    user_id: str = TEST_USER_ID,
    name: str | None = "Ada Lovelace",
    status: str = "unresolved",
) -> int:
    conflict_id: int = (
        await connection.execute(
            text("""
                INSERT INTO pending_entity_mappings
                    (user_id, integration_source, external_entity_id,
                     external_entity_name, candidate_contact_ids, status)
                VALUES (:user_id, 'immich', :person_id, :name, '[]'::jsonb,
                        :status)
                RETURNING id
            """),
            {
                "user_id": user_id,
                "person_id": PERSON_ID,
                "name": name,
                "status": status,
            },
        )
    ).scalar_one()
    return conflict_id


async def _conflict_state(
    connection: AsyncConnection, conflict_id: int
) -> tuple[str, int | None]:
    row = (
        await connection.execute(
            text(
                "SELECT status, resolved_contact_id FROM pending_entity_mappings"
                " WHERE id = :id"
            ),
            {"id": conflict_id},
        )
    ).one()
    return row.status, row.resolved_contact_id


async def _linked_contact(connection: AsyncConnection) -> tuple[int, str] | None:
    row = (
        await connection.execute(
            text(
                "SELECT internal_id, user_id FROM sync_metadata"
                " WHERE integration_source = 'immich' AND external_id = :person"
                "   AND user_id = :user_id"
            ),
            {"person": PERSON_ID, "user_id": TEST_USER_ID},
        )
    ).one_or_none()
    return None if row is None else (row.internal_id, row.user_id)


async def _contact_names(
    connection: AsyncConnection, contact_id: int
) -> tuple[str, str | None, str]:
    row = (
        await connection.execute(
            text("SELECT first_name, last_name, user_id FROM contacts WHERE id = :id"),
            {"id": contact_id},
        )
    ).one()
    return row.first_name, row.last_name, row.user_id


async def _contact_count(connection: AsyncConnection) -> int:
    count: int = (
        await connection.execute(
            text("SELECT count(*) FROM contacts WHERE user_id = :user_id"),
            {"user_id": TEST_USER_ID},
        )
    ).scalar_one()
    return count


@pytest.mark.integration
@pytest.mark.asyncio
async def test_link_resolves_the_conflict_to_the_users_contact(
    async_connection: AsyncConnection, service: ImmichConflictResolutionService
) -> None:
    conflict_id = await _seed_conflict(async_connection)
    contact_id = await seed_contact(async_connection, first_name="Ada")

    resolved = await service.resolve(
        conflict_id,
        ConflictResolutionAction.LINK,
        contact_id,
        user_id=TEST_USER_ID,
        provenance=Provenance.UI,
        transaction=async_connection,
    )

    assert resolved.contact_id == contact_id
    assert resolved.conflict_id == conflict_id
    assert resolved.external_entity_id == PERSON_ID
    assert resolved.status == "resolved"
    assert await _conflict_state(async_connection, conflict_id) == (
        "resolved",
        contact_id,
    )
    assert await _linked_contact(async_connection) == (contact_id, TEST_USER_ID)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_splits_the_immich_name_on_its_last_space(
    async_connection: AsyncConnection, service: ImmichConflictResolutionService
) -> None:
    conflict_id = await _seed_conflict(async_connection, name="John Michael Smith")

    resolved = await service.resolve(
        conflict_id,
        ConflictResolutionAction.CREATE,
        None,
        user_id=TEST_USER_ID,
        provenance=Provenance.MCP,
        transaction=async_connection,
    )

    assert await _contact_names(async_connection, resolved.contact_id) == (
        "John Michael",
        "Smith",
        TEST_USER_ID,
    )
    assert await _linked_contact(async_connection) == (
        resolved.contact_id,
        TEST_USER_ID,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_names_a_nameless_person_unnamed(
    async_connection: AsyncConnection, service: ImmichConflictResolutionService
) -> None:
    conflict_id = await _seed_conflict(async_connection, name="   ")

    resolved = await service.resolve(
        conflict_id,
        ConflictResolutionAction.CREATE,
        None,
        user_id=TEST_USER_ID,
        provenance=Provenance.UI,
        transaction=async_connection,
    )

    first_name, last_name, _ = await _contact_names(
        async_connection, resolved.contact_id
    )
    assert first_name == "Unnamed"
    assert not last_name


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("owner", "status"),
    [(OTHER_USER_ID, "unresolved"), (TEST_USER_ID, "resolved")],
    ids=["another-users-conflict", "already-resolved"],
)
async def test_a_conflict_the_user_cannot_resolve_is_not_found(
    async_connection: AsyncConnection,
    service: ImmichConflictResolutionService,
    owner: str,
    status: str,
) -> None:
    conflict_id = await _seed_conflict(async_connection, user_id=owner, status=status)
    contact_id = await seed_contact(async_connection)

    with pytest.raises(ImmichConflictNotFoundError):
        await service.resolve(
            conflict_id,
            ConflictResolutionAction.LINK,
            contact_id,
            user_id=TEST_USER_ID,
            provenance=Provenance.UI,
            transaction=async_connection,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_missing_conflict_is_not_found(
    async_connection: AsyncConnection, service: ImmichConflictResolutionService
) -> None:
    with pytest.raises(ImmichConflictNotFoundError):
        await service.resolve(
            999_999,
            ConflictResolutionAction.CREATE,
            None,
            user_id=TEST_USER_ID,
            provenance=Provenance.UI,
            transaction=async_connection,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_link_to_another_users_contact_is_refused(
    async_connection: AsyncConnection, service: ImmichConflictResolutionService
) -> None:
    conflict_id = await _seed_conflict(async_connection)
    their_contact_id = await seed_contact(async_connection, user_id=OTHER_USER_ID)

    with pytest.raises(ContactNotFoundError):
        await service.resolve(
            conflict_id,
            ConflictResolutionAction.LINK,
            their_contact_id,
            user_id=TEST_USER_ID,
            provenance=Provenance.UI,
            transaction=async_connection,
        )

    assert await _conflict_state(async_connection, conflict_id) == (
        "unresolved",
        None,
    )
    assert await _linked_contact(async_connection) is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_link_without_a_contact_is_refused(
    async_connection: AsyncConnection, service: ImmichConflictResolutionService
) -> None:
    conflict_id = await _seed_conflict(async_connection)

    with pytest.raises(ImmichConflictContactRequiredError):
        await service.resolve(
            conflict_id,
            ConflictResolutionAction.LINK,
            None,
            user_id=TEST_USER_ID,
            provenance=Provenance.UI,
            transaction=async_connection,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_failed_link_write_rolls_back_the_contact_and_resolution(
    async_connection: AsyncConnection,
) -> None:
    conflict_id = await _seed_conflict(async_connection)
    contacts_before = await _contact_count(async_connection)
    service = _service(
        async_connection, FailingSyncMetadataRepository(async_connection)
    )

    with pytest.raises(RuntimeError, match="link store unavailable"):
        await service.resolve(
            conflict_id,
            ConflictResolutionAction.CREATE,
            None,
            user_id=TEST_USER_ID,
            provenance=Provenance.UI,
            transaction=async_connection,
        )

    assert await _contact_count(async_connection) == contacts_before
    assert await _conflict_state(async_connection, conflict_id) == (
        "unresolved",
        None,
    )
