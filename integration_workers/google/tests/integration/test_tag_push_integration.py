"""
Integration tests for tag push functions against a real database.

Tests that raw SQL queries in _load_tag_names_for_contact and
_load_full_contact execute correctly against the actual schema.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import _load_full_contact, _load_tag_names_for_contact


@pytest_asyncio.fixture
async def contact_with_tags(db_session: AsyncSession) -> dict[str, int]:
    """Create a contact with tags assigned in the real database.

    Returns:
        Dict with contact_id and tag IDs for assertions.
    """
    # Create a contact
    result = await db_session.execute(
        text(
            """
            INSERT INTO contacts (first_name, last_name)
            VALUES ('Test', 'TagPush')
            RETURNING id
            """
        )
    )
    contact_id = result.scalar_one()

    # Create tags
    result = await db_session.execute(
        text(
            """
            INSERT INTO tags (name) VALUES ('work')
            RETURNING id
            """
        )
    )
    work_tag_id = result.scalar_one()

    result = await db_session.execute(
        text(
            """
            INSERT INTO tags (name) VALUES ('friend')
            RETURNING id
            """
        )
    )
    friend_tag_id = result.scalar_one()

    # Assign tags to contact
    await db_session.execute(
        text(
            """
            INSERT INTO contact_tags (contact_id, tag_id)
            VALUES (:cid, :tid1), (:cid, :tid2)
            """
        ),
        {"cid": contact_id, "tid1": work_tag_id, "tid2": friend_tag_id},
    )
    await db_session.flush()

    return {
        "contact_id": contact_id,
        "work_tag_id": work_tag_id,
        "friend_tag_id": friend_tag_id,
    }


@pytest.mark.asyncio
class TestLoadTagNamesForContactIntegration:
    """Integration tests for _load_tag_names_for_contact with real database."""

    async def test_loads_tag_names_for_contact(
        self, db_session: AsyncSession, contact_with_tags: dict[str, int]
    ) -> None:
        """Test that tag names are correctly loaded from the database."""
        contact_id = contact_with_tags["contact_id"]

        tag_names = await _load_tag_names_for_contact(db_session, contact_id)

        # Should return alphabetically sorted tag names
        assert tag_names == ["friend", "work"]

    async def test_returns_empty_list_for_contact_without_tags(
        self, db_session: AsyncSession
    ) -> None:
        """Test that an empty list is returned for a contact with no tags."""
        # Create a contact with no tags
        result = await db_session.execute(
            text(
                """
                INSERT INTO contacts (first_name, last_name)
                VALUES ('NoTag', 'Contact')
                RETURNING id
                """
            )
        )
        contact_id = result.scalar_one()
        await db_session.flush()

        tag_names = await _load_tag_names_for_contact(db_session, contact_id)

        assert tag_names == []

    async def test_returns_empty_list_for_nonexistent_contact(
        self, db_session: AsyncSession
    ) -> None:
        """Test that a nonexistent contact ID returns an empty list."""
        tag_names = await _load_tag_names_for_contact(db_session, contact_id=999999)

        assert tag_names == []

    async def test_returns_sorted_tag_names(
        self, db_session: AsyncSession
    ) -> None:
        """Test that tag names are returned in alphabetical order."""
        # Create contact
        result = await db_session.execute(
            text(
                """
                INSERT INTO contacts (first_name, last_name)
                VALUES ('Sort', 'Test')
                RETURNING id
                """
            )
        )
        contact_id = result.scalar_one()

        # Create tags in non-alphabetical order
        for tag_name in ["zebra", "alpha", "middle"]:
            tag_result = await db_session.execute(
                text("INSERT INTO tags (name) VALUES (:name) RETURNING id"),
                {"name": tag_name},
            )
            tag_id = tag_result.scalar_one()
            await db_session.execute(
                text(
                    "INSERT INTO contact_tags (contact_id, tag_id) VALUES (:cid, :tid)"
                ),
                {"cid": contact_id, "tid": tag_id},
            )
        await db_session.flush()

        tag_names = await _load_tag_names_for_contact(db_session, contact_id)

        assert tag_names == ["alpha", "middle", "zebra"]


@pytest.mark.asyncio
class TestLoadFullContactIntegration:
    """Integration tests for _load_full_contact with real database."""

    async def test_load_full_contact_includes_tags(
        self, db_session: AsyncSession, contact_with_tags: dict[str, int]
    ) -> None:
        """Test that _load_full_contact returns tag names in the result."""
        contact_id = contact_with_tags["contact_id"]

        result = await _load_full_contact(db_session, contact_id)

        assert "tags" in result
        assert result["tags"] == ["friend", "work"]

    async def test_load_full_contact_returns_all_sections(
        self, db_session: AsyncSession
    ) -> None:
        """Test that _load_full_contact returns methods, addresses, notes, and tags."""
        # Create a contact with a method, address, note, and tag
        result = await db_session.execute(
            text(
                """
                INSERT INTO contacts (first_name, last_name)
                VALUES ('Full', 'Load')
                RETURNING id
                """
            )
        )
        contact_id = result.scalar_one()

        # Add email method
        await db_session.execute(
            text(
                """
                INSERT INTO contact_methods (contact_id, method_type, value, is_primary)
                VALUES (:cid, 'email', 'full@load.com', true)
                """
            ),
            {"cid": contact_id},
        )

        # Add address
        await db_session.execute(
            text(
                """
                INSERT INTO contact_addresses (contact_id, street_line_1,
                    locality, country_code, is_primary)
                VALUES (:cid, '123 Test St', 'TestCity', 'AU', true)
                """
            ),
            {"cid": contact_id},
        )

        # Add note
        await db_session.execute(
            text(
                """
                INSERT INTO contact_notes (contact_id, content)
                VALUES (:cid, 'Test note')
                """
            ),
            {"cid": contact_id},
        )

        # Add tag
        tag_result = await db_session.execute(
            text("INSERT INTO tags (name) VALUES ('loaded') RETURNING id")
        )
        tag_id = tag_result.scalar_one()
        await db_session.execute(
            text(
                "INSERT INTO contact_tags (contact_id, tag_id) VALUES (:cid, :tid)"
            ),
            {"cid": contact_id, "tid": tag_id},
        )
        await db_session.flush()

        full_data = await _load_full_contact(db_session, contact_id)

        assert len(full_data["methods"]) == 1
        assert full_data["methods"][0]["value"] == "full@load.com"
        assert len(full_data["addresses"]) == 1
        assert full_data["addresses"][0]["locality"] == "TestCity"
        assert len(full_data["notes"]) == 1
        assert full_data["notes"][0]["content"] == "Test note"
        assert full_data["tags"] == ["loaded"]

    async def test_load_full_contact_empty_tags(
        self, db_session: AsyncSession
    ) -> None:
        """Test that _load_full_contact returns empty tags for tagless contact."""
        result = await db_session.execute(
            text(
                """
                INSERT INTO contacts (first_name, last_name)
                VALUES ('NoTag', 'Full')
                RETURNING id
                """
            )
        )
        contact_id = result.scalar_one()
        await db_session.flush()

        full_data = await _load_full_contact(db_session, contact_id)

        assert full_data["tags"] == []
        assert full_data["methods"] == []
        assert full_data["addresses"] == []
        assert full_data["notes"] == []
