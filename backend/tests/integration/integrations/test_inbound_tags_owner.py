"""Inbound contact syncs resolve tags within the event owner's tags.

Contact tags are per user, so a Google group name names a tag of the user whose
account it is. Another user's tag of the same name is a different tag: the
inbound processor must neither attach it nor be stopped by it.
"""

from __future__ import annotations

import pytest
from core_shared.models.contacts.entities import Tag
from core_shared.models.contacts.value_objects import TagName
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import SqlTagRepository
from app.core.integrations.outbox_event_processor import OutboxEventProcessor
from tests.integration.contact_seeding import OTHER_USER_ID, TEST_USER_ID
from tests.integration.integrations.link_consolidation_helpers import (
    build_contact_service,
)


@pytest.mark.integration
@pytest.mark.usefixtures("clean_database")
class TestInboundTagsBelongToTheEventOwner:
    @pytest.mark.asyncio
    async def test_a_group_name_another_user_holds_creates_the_owners_own_tag(
        self, async_connection: AsyncConnection
    ) -> None:
        theirs = await SqlTagRepository(async_connection).save(
            Tag(name=TagName("Family")), user_id=TEST_USER_ID
        )
        event = OutboxEvent.create_contact_sync_event(
            contact_data={
                "user_id": OTHER_USER_ID,
                "first_name": "Ann",
                "tags": [{"name": "Family"}],
            },
            integration_source="google",
            external_id="people/cInboundTag",
            sync_type="created",
            etag="etag-1",
            user_id=OTHER_USER_ID,
        )

        result = await OutboxEventProcessor(
            build_contact_service(async_connection), async_connection
        ).process_event(event)

        assert result["status"] == "success"
        rows = (
            await async_connection.execute(
                text(
                    """
                    SELECT t.id, t.user_id FROM tags t
                    JOIN contact_tags ct ON ct.tag_id = t.id
                    JOIN contacts c ON c.id = ct.contact_id
                    WHERE c.first_name = 'Ann'
                    """
                )
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].id != theirs.id
        assert rows[0].user_id == OTHER_USER_ID
