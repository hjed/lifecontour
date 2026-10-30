"""Integration tests for the Immich person's synced base (#1900).

The push records the base and ``pending_import`` on the real link.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from core_shared.repositories.integration_link_repository import (
    IntegrationLinkRepository,
)
from core_shared.sync_base import (
    PENDING_IMPORT_KEY,
    SYNCED_ENTRIES_KEY,
    serialise_synced_entries,
)
from core_shared.testing.seeding import seed_contact
from sqlalchemy import text

from immich_models import ImmichPerson
from immich_sync_service import ImmichSyncService
from person_base import birth_date_keys, name_keys

USER_ID = "test-user-synced-base"
PERSON_ID = "44444444-4444-4444-8444-444444444444"


def _service(connection: Any, api: Any | None = None) -> ImmichSyncService:
    return ImmichSyncService(
        api_client=api or AsyncMock(),
        connection=connection,
        user_id=USER_ID,
        integration_source="immich",
    )


async def _link(
    connection: Any,
    service: ImmichSyncService,
    contact_id: int,
    *,
    person: ImmichPerson,
    reference_data: dict[str, Any],
    synced_at: datetime | None = None,
) -> None:
    """Link ``person`` to the contact, in step with it, recording ``reference_data``."""
    await service._upsert_sync_metadata(
        external_id=person.id,
        internal_id=contact_id,
        version_hash=service.calculate_version_hash(person),
        synced_at=synced_at,
    )
    await IntegrationLinkRepository(connection).patch_reference_data(
        "immich", person.id, reference_data, user_id=USER_ID
    )


async def _link_row(connection: Any) -> Any:
    result = await connection.execute(
        text(
            "SELECT reference_data, last_synced_at FROM sync_metadata "
            "WHERE user_id = :user_id AND external_id = :external_id"
        ),
        {"user_id": USER_ID, "external_id": PERSON_ID},
    )
    return result.one()


class TestPushRecordsTheBase:
    @pytest.mark.asyncio
    async def test_push_records_base_flag_and_contact_version(
        self, async_connection: Any
    ) -> None:
        """Immich changed the birthday since the base: kept, and left for the pull."""
        contact_id = await seed_contact(
            async_connection, first_name="Ada", last_name="Lovelace", user_id=USER_ID
        )
        await async_connection.execute(
            text(
                "INSERT INTO contact_important_dates "
                "(contact_id, date_type, precision, year, month, day) "
                "VALUES (:contact_id, 'birthday', 'full', 1815, 12, 10)"
            ),
            {"contact_id": contact_id},
        )
        current = ImmichPerson(
            id=PERSON_ID, name="Ada Lovelace", birth_date="1815-12-11"
        )
        api: Any = AsyncMock()
        api.get_person.return_value = current
        service = _service(async_connection, api)
        await _link(
            async_connection,
            service,
            contact_id,
            person=current,
            reference_data={
                SYNCED_ENTRIES_KEY: serialise_synced_entries(
                    {
                        "name": name_keys("Ada Lovelace"),
                        "birthDate": birth_date_keys("1815-12-10"),
                    }
                )
            },
        )

        result = await service.sync_contact_outbound(contact_id)

        assert result["status"] == "success"
        api.update_person.assert_not_called()
        row = await _link_row(async_connection)
        reference_data = json.loads(row.reference_data)
        assert reference_data[PENDING_IMPORT_KEY] is True
        assert reference_data[SYNCED_ENTRIES_KEY] == serialise_synced_entries(
            {
                "name": name_keys("Ada Lovelace"),
                "birthDate": birth_date_keys("1815-12-10"),
            }
        )
        contact_updated_at = (
            await async_connection.execute(
                text("SELECT updated_at FROM contacts WHERE id = :id"),
                {"id": contact_id},
            )
        ).scalar_one()
        assert row.last_synced_at == contact_updated_at

    @pytest.mark.asyncio
    async def test_birthday_changed_in_immich_during_the_push_is_left_for_the_pull(
        self, async_connection: Any
    ) -> None:
        """Agreed at the GET, but the name-only PUT's response holds a new birthday."""
        contact_id = await seed_contact(
            async_connection, first_name="Ada", last_name="King", user_id=USER_ID
        )
        before = ImmichPerson(id=PERSON_ID, name="Ada Lovelace")
        api: Any = AsyncMock()
        api.get_person.return_value = before
        api.update_person.return_value = ImmichPerson(
            id=PERSON_ID, name="Ada King", birth_date="1815-12-11"
        )
        service = _service(async_connection, api)
        await _link(
            async_connection,
            service,
            contact_id,
            person=before,
            reference_data={
                SYNCED_ENTRIES_KEY: serialise_synced_entries(
                    {"name": name_keys("Ada Lovelace"), "birthDate": frozenset()}
                )
            },
        )

        await service.sync_contact_outbound(contact_id)

        api.update_person.assert_awaited_once_with(PERSON_ID, {"name": "Ada King"})
        reference_data = json.loads((await _link_row(async_connection)).reference_data)
        assert reference_data[PENDING_IMPORT_KEY] is True
        assert reference_data[SYNCED_ENTRIES_KEY] == serialise_synced_entries(
            {"name": name_keys("Ada King"), "birthDate": frozenset()}
        )
