"""A contact that really is committed, for tests that overlap two connections."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from core_shared.models.contacts.entities import Contact
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.contacts.services.contact_service import ContactService
from tests.integration.contacts.contact_service_harness import (
    RecordingEventPublisher,
    build_contact_service,
)


@asynccontextmanager
async def committed_contact(
    async_engine: AsyncEngine, **fields: str | bool | None
) -> AsyncIterator[tuple[str, int]]:
    """A contact committed under an owner nobody else will see, deleted afterwards.

    Services built with :func:`contact_service_on` record their events rather
    than writing them to the outbox, so the contact's own rows are all there is
    to clean up.

    Yields:
        ``(user_id, contact_id)``.
    """
    user_id = f"race-{uuid4()}"
    async with async_engine.connect() as setup:
        saved = await SqlContactRepository(setup).save(
            Contact(user_id=user_id, **{"first_name": "Ada", **fields})  # type: ignore[arg-type]
        )
        await setup.commit()
    assert saved.id is not None

    try:
        yield user_id, saved.id
    finally:
        async with async_engine.connect() as cleanup:
            await cleanup.execute(
                text("DELETE FROM contacts WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
            await cleanup.commit()


def contact_service_on(connection: AsyncConnection) -> ContactService:
    """A ``ContactService`` over the real repositories on ``connection``."""
    return build_contact_service(connection, RecordingEventPublisher())


async def stored_contact(
    async_engine: AsyncEngine, contact_id: int, user_id: str
) -> Contact:
    """The contact as committed, read on a connection of its own."""
    async with async_engine.connect() as check:
        contact = await SqlContactRepository(check).find_by_id(
            contact_id, user_id=user_id
        )
    assert contact is not None
    return contact
