"""The shared contact seeding helper, against a real database.

Every integration test that needs a contact row seeds it through
``seed_contact``, so these pin down what that row looks like: the defaults a
bare call produces, and that every column a caller names is written as given.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.auth.models import SessionUser
from tests.integration.contact_seeding import TEST_USER_ID, seed_contact, seed_contacts

pytestmark = pytest.mark.asyncio

_SELECT_CONTACT = text("""
    SELECT id, user_id, first_name, last_name, middle_name, nick_name, company,
           job_title, photo_url, is_favourite, created_at, updated_at
    FROM contacts
    WHERE id = :id
""")


async def _row(connection: AsyncConnection, contact_id: int) -> Row[Any]:
    return (await connection.execute(_SELECT_CONTACT, {"id": contact_id})).one()


async def test_a_bare_call_seeds_a_minimal_contact(
    async_connection: AsyncConnection,
) -> None:
    contact_id = await seed_contact(async_connection)

    row = await _row(async_connection, contact_id)
    assert row.user_id == TEST_USER_ID
    assert row.first_name == "Sarah"
    assert row.last_name is None
    assert row.is_favourite is False
    assert row.created_at is not None
    assert row.updated_at is not None


async def test_bare_calls_get_distinct_ids(async_connection: AsyncConnection) -> None:
    first = await seed_contact(async_connection)
    second = await seed_contact(async_connection)

    assert first != second


async def test_every_named_column_is_written(async_connection: AsyncConnection) -> None:
    created_at = datetime(2024, 3, 1, 9, 0, tzinfo=UTC)
    updated_at = datetime(2025, 4, 2, 10, 30, tzinfo=UTC)

    contact_id = await seed_contact(
        async_connection,
        first_name="Ada",
        middle_name="Byron",
        last_name="Lovelace",
        nick_name="Countess",
        company="Analytical Engines",
        job_title="Mathematician",
        photo_url="https://example.com/ada.jpg",
        is_favourite=True,
        created_at=created_at,
        updated_at=updated_at,
    )

    row = await _row(async_connection, contact_id)
    assert (
        row.first_name,
        row.middle_name,
        row.last_name,
        row.nick_name,
        row.company,
        row.job_title,
        row.photo_url,
        row.is_favourite,
        row.created_at,
        row.updated_at,
    ) == (
        "Ada",
        "Byron",
        "Lovelace",
        "Countess",
        "Analytical Engines",
        "Mathematician",
        "https://example.com/ada.jpg",
        True,
        created_at,
        updated_at,
    )


async def test_an_explicit_owner_is_written(async_connection: AsyncConnection) -> None:
    contact_id = await seed_contact(async_connection, user_id="other-user-456")

    assert (await _row(async_connection, contact_id)).user_id == "other-user-456"


async def test_an_explicit_id_is_used_and_returned(
    async_connection: AsyncConnection,
) -> None:
    contact_id = await seed_contact(async_connection, contact_id=987_654)

    assert contact_id == 987_654
    assert (await _row(async_connection, 987_654)).first_name == "Sarah"


async def test_the_test_user_fixture_is_the_seeding_owner(
    test_user: SessionUser,
) -> None:
    assert test_user.id == TEST_USER_ID


async def test_bulk_seeding_numbers_the_contacts_in_one_statement(
    async_connection: AsyncConnection,
) -> None:
    contact_ids = await seed_contacts(async_connection, 3, first_name_prefix="Guest")

    assert len(set(contact_ids)) == 3
    rows = [await _row(async_connection, i) for i in contact_ids]
    assert [row.first_name for row in rows] == ["Guest 1", "Guest 2", "Guest 3"]
    assert {row.user_id for row in rows} == {TEST_USER_ID}
