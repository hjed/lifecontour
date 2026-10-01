"""
Integration tests for tag push functions against a real database.

Tests that raw SQL queries in _load_tag_names_for_contact,
_load_tag_names_for_contacts_batch, and _load_full_contact execute
correctly against the actual schema.
"""

import pytest
import pytest_asyncio
from core_shared.testing.seeding import seed_contact
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import (
    _load_full_contact,
    _load_tag_names_for_contact,
    _load_tag_names_for_contacts_batch,
)


@pytest_asyncio.fixture
async def contact_with_tags(db_session: AsyncSession) -> dict[str, int]:
    """Create a contact with tags assigned in the real database.

    Returns:
        Dict with contact_id and tag IDs for assertions.
    """
    # Create a contact
    contact_id = await seed_contact(db_session, first_name="Test", last_name="TagPush")

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
        contact_id = await seed_contact(
            db_session, first_name="NoTag", last_name="Contact"
        )
        await db_session.flush()

        tag_names = await _load_tag_names_for_contact(db_session, contact_id)

        assert tag_names == []

    async def test_returns_empty_list_for_nonexistent_contact(
        self, db_session: AsyncSession
    ) -> None:
        """Test that a nonexistent contact ID returns an empty list."""
        tag_names = await _load_tag_names_for_contact(db_session, contact_id=999999)

        assert tag_names == []

    async def test_returns_sorted_tag_names(self, db_session: AsyncSession) -> None:
        """Test that tag names are returned in alphabetical order."""
        # Create contact
        contact_id = await seed_contact(db_session, first_name="Sort", last_name="Test")

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
        contact_id = await seed_contact(db_session, first_name="Full", last_name="Load")

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
            text("INSERT INTO contact_tags (contact_id, tag_id) VALUES (:cid, :tid)"),
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

    async def test_load_full_contact_empty_tags(self, db_session: AsyncSession) -> None:
        """Test that _load_full_contact returns empty tags for tagless contact."""
        contact_id = await seed_contact(
            db_session, first_name="NoTag", last_name="Full"
        )
        await db_session.flush()

        full_data = await _load_full_contact(db_session, contact_id)

        assert full_data["tags"] == []
        assert full_data["methods"] == []
        assert full_data["addresses"] == []
        assert full_data["notes"] == []


@pytest.mark.asyncio
class TestLoadTagNamesForContactsBatchIntegration:
    """Integration tests for batch tag loading with real database."""

    async def test_batch_loads_tags_for_multiple_contacts(
        self, db_session: AsyncSession
    ) -> None:
        """Test that batch loading retrieves tags for several contacts."""
        # Create two contacts
        cid1 = await seed_contact(db_session, first_name="Batch", last_name="One")

        cid2 = await seed_contact(db_session, first_name="Batch", last_name="Two")

        # Create tags
        t1 = (
            await db_session.execute(
                text("INSERT INTO tags (name) VALUES ('alpha') RETURNING id")
            )
        ).scalar_one()
        t2 = (
            await db_session.execute(
                text("INSERT INTO tags (name) VALUES ('beta') RETURNING id")
            )
        ).scalar_one()

        # Assign: contact 1 gets both, contact 2 gets beta only
        await db_session.execute(
            text(
                "INSERT INTO contact_tags (contact_id, tag_id) "
                "VALUES (:c1, :t1), (:c1, :t2), (:c2, :t2)"
            ),
            {"c1": cid1, "t1": t1, "t2": t2, "c2": cid2},
        )
        await db_session.flush()

        result = await _load_tag_names_for_contacts_batch(db_session, [cid1, cid2])

        assert result[cid1] == ["alpha", "beta"]
        assert result[cid2] == ["beta"]

    async def test_batch_returns_empty_for_tagless_contacts(
        self, db_session: AsyncSession
    ) -> None:
        """Test that contacts with no tags get empty lists in batch result."""
        cid = await seed_contact(db_session, first_name="NoTag", last_name="Batch")
        await db_session.flush()

        result = await _load_tag_names_for_contacts_batch(db_session, [cid])

        assert result[cid] == []

    async def test_batch_empty_input(self, db_session: AsyncSession) -> None:
        """Test that empty input returns empty dict without querying."""
        result = await _load_tag_names_for_contacts_batch(db_session, [])

        assert result == {}


@pytest.mark.asyncio
class TestLoadFullContactArchived:
    """Archived values are loaded with their flag, so the push can leave them out."""

    async def test_archived_values_carry_is_archived(
        self, db_session: AsyncSession
    ) -> None:
        from worker import _transform_contact_to_google_person

        contact_id = await seed_contact(db_session, first_name="Arch")
        await db_session.execute(
            text(
                """
                INSERT INTO contact_methods
                    (contact_id, method_type, value, is_primary, is_archived)
                VALUES (:cid, 'email', 'now@example.com', true, false),
                       (:cid, 'email', 'then@example.com', false, true)
                """
            ),
            {"cid": contact_id},
        )
        await db_session.execute(
            text(
                """
                INSERT INTO contact_addresses
                    (contact_id, street_line_1, country_code, is_archived)
                VALUES (:cid, '1 Childhood Rd', 'AU', true)
                """
            ),
            {"cid": contact_id},
        )

        loaded = await _load_full_contact(db_session, contact_id)

        assert {m["value"]: m["is_archived"] for m in loaded["methods"]} == {
            "now@example.com": False,
            "then@example.com": True,
        }
        assert [a["is_archived"] for a in loaded["addresses"]] == [True]

        person = _transform_contact_to_google_person(loaded)
        assert [e["value"] for e in person["emailAddresses"]] == ["now@example.com"]
        assert person["addresses"] == []
