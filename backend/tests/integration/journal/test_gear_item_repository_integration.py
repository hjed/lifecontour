"""Integration tests for GearItemRepository."""

from datetime import date

import pytest
import pytest_asyncio
from core_shared.models.journals import GearItem

from app.core.journal.adapters.sql.gear_item_repository import SqlGearItemRepository


@pytest.mark.integration
class TestGearItemRepositoryIntegration:
    """Integration tests for SqlGearItemRepository against real database."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Ensure clean database for each test."""
        pass

    @pytest_asyncio.fixture
    async def repo(self, async_connection):
        """Create a SqlGearItemRepository instance."""
        return SqlGearItemRepository(async_connection)

    async def test_save_new_gear_item(self, repo):
        """Test saving a new gear item and verifying returned entity."""
        item = GearItem(
            name="Climbing Rope 60m",
            user_id="test-user-1",
            model="Beal Stinger III",
            serial_number="SN-12345",
            purchase_date=date(2025, 6, 15),
            manufacturer="Beal",
        )
        saved = await repo.save(item)

        assert saved.id is not None
        assert saved.name == "Climbing Rope 60m"
        assert saved.user_id == "test-user-1"
        assert saved.model == "Beal Stinger III"
        assert saved.serial_number == "SN-12345"
        assert saved.purchase_date == date(2025, 6, 15)
        assert saved.manufacturer == "Beal"
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_and_find_by_id(self, repo):
        """Test saving a gear item and finding it by ID."""
        item = GearItem(name="Harness", user_id="test-user-1")
        saved = await repo.save(item)

        found = await repo.find_by_id(saved.id)
        assert found is not None
        assert found.id == saved.id
        assert found.name == "Harness"
        assert found.user_id == "test-user-1"

    async def test_find_by_id_not_found(self, repo):
        """Test finding by ID returns None for non-existent item."""
        found = await repo.find_by_id("550e8400-e29b-41d4-a716-446655440000")
        assert found is None

    async def test_save_update_existing(self, repo):
        """Test updating an existing gear item via save."""
        item = GearItem(
            name="Old Rope",
            user_id="test-user-1",
            model="Model A",
        )
        saved = await repo.save(item)

        # Update fields
        saved.name = "New Rope"
        saved.model = "Model B"
        saved.manufacturer = "Petzl"
        updated = await repo.save(saved)

        assert updated.id == saved.id
        assert updated.name == "New Rope"
        assert updated.model == "Model B"
        assert updated.manufacturer == "Petzl"

    async def test_find_by_user(self, repo):
        """Test finding all gear items for a user, ordered by name."""
        # Create items in non-alphabetical order
        await repo.save(GearItem(name="Rope", user_id="test-user-1"))
        await repo.save(GearItem(name="Carabiner", user_id="test-user-1"))
        await repo.save(GearItem(name="Harness", user_id="test-user-1"))
        # Different user
        await repo.save(GearItem(name="Other Rope", user_id="test-user-2"))

        items = await repo.find_by_user("test-user-1")
        assert len(items) == 3
        # Should be ordered alphabetically
        assert items[0].name == "Carabiner"
        assert items[1].name == "Harness"
        assert items[2].name == "Rope"

    async def test_find_by_user_empty(self, repo):
        """Test finding gear items for a user with no items."""
        items = await repo.find_by_user("nonexistent-user")
        assert items == []

    async def test_search_by_name(self, repo):
        """Test searching gear items by name (case-insensitive partial match)."""
        await repo.save(GearItem(name="Climbing Rope 60m", user_id="test-user-1"))
        await repo.save(GearItem(name="Climbing Harness", user_id="test-user-1"))
        await repo.save(GearItem(name="Helmet", user_id="test-user-1"))
        await repo.save(GearItem(name="climbing rope 50m", user_id="test-user-2"))

        # Case-insensitive search
        results = await repo.search_by_name("test-user-1", "climbing")
        assert len(results) == 2
        assert results[0].name == "Climbing Harness"
        assert results[1].name == "Climbing Rope 60m"

    async def test_search_by_name_partial(self, repo):
        """Test partial name matching in search."""
        await repo.save(GearItem(name="Petzl Harness", user_id="test-user-1"))
        await repo.save(GearItem(name="Black Diamond Harness", user_id="test-user-1"))
        await repo.save(GearItem(name="Rope", user_id="test-user-1"))

        results = await repo.search_by_name("test-user-1", "harness")
        assert len(results) == 2

    async def test_search_by_name_no_results(self, repo):
        """Test search returns empty list when no matches found."""
        await repo.save(GearItem(name="Rope", user_id="test-user-1"))
        results = await repo.search_by_name("test-user-1", "xyz")
        assert results == []

    async def test_delete_gear_item(self, repo):
        """Test deleting a gear item."""
        item = GearItem(name="To Delete", user_id="test-user-1")
        saved = await repo.save(item)

        await repo.delete(saved.id)

        found = await repo.find_by_id(saved.id)
        assert found is None

    async def test_delete_nonexistent_no_error(self, repo):
        """Test deleting a non-existent gear item does not raise an error."""
        # Should not raise
        await repo.delete("550e8400-e29b-41d4-a716-446655440000")

    async def test_save_with_all_nullable_fields(self, repo):
        """Test saving a gear item with all nullable fields set."""
        item = GearItem(
            name="Full Gear",
            user_id="test-user-1",
            model="Pro Model",
            serial_number="SN-99999",
            purchase_date=date(2024, 1, 1),
            manufacturer="DMM",
        )
        saved = await repo.save(item)

        found = await repo.find_by_id(saved.id)
        assert found is not None
        assert found.model == "Pro Model"
        assert found.serial_number == "SN-99999"
        assert found.purchase_date == date(2024, 1, 1)
        assert found.manufacturer == "DMM"

    async def test_save_with_no_optional_fields(self, repo):
        """Test saving a gear item with no optional fields."""
        item = GearItem(name="Minimal Gear", user_id="test-user-1")
        saved = await repo.save(item)

        found = await repo.find_by_id(saved.id)
        assert found is not None
        assert found.model is None
        assert found.serial_number is None
        assert found.purchase_date is None
        assert found.manufacturer is None
