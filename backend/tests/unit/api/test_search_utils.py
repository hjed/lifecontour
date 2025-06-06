"""
Tests for search API utilities.

Tests the helper functions used to reduce code duplication in search controllers.
"""

from app.api.search.utils import (
    calculate_pagination_offset,
    create_contact_resource_from_search_hit,
)


class TestCalculatePaginationOffset:
    """Test pagination offset calculation."""

    def test_first_page(self):
        """Test offset calculation for first page."""
        assert calculate_pagination_offset(1, 20) == 0

    def test_second_page(self):
        """Test offset calculation for second page."""
        assert calculate_pagination_offset(2, 20) == 20

    def test_third_page_different_limit(self):
        """Test offset calculation for third page with different limit."""
        assert calculate_pagination_offset(3, 10) == 20

    def test_large_page_number(self):
        """Test offset calculation for large page number."""
        assert calculate_pagination_offset(100, 25) == 2475


class TestCreateContactResourceFromSearchHit:
    """Test contact resource creation from search hits."""

    def test_minimal_hit(self):
        """Test creating contact resource from minimal search hit."""
        hit = {
            "id": 123,
            "first_name": "John",
        }
        base_url = "https://api.example.com"

        resource = create_contact_resource_from_search_hit(hit, base_url)

        assert resource.type == "contacts"
        assert resource.id == "123"
        assert resource.attributes.first_name == "John"
        assert resource.attributes.last_name is None
        assert resource.links is not None
        assert resource.links.self == "https://api.example.com/api/contacts/123"
        assert resource.meta is not None
        assert resource.meta["search_score"] is None
        assert resource.meta["search_metadata"]["tags"] == []

    def test_complete_hit(self):
        """Test creating contact resource from complete search hit."""
        hit = {
            "id": 456,
            "first_name": "Jane",
            "last_name": "Doe",
            "middle_name": "Marie",
            "nick_name": "Janie",
            "created_at": "2023-01-01T00:00:00Z",
            "updated_at": "2023-01-02T00:00:00Z",
            "tags": ["friend", "work"],
            "email": "jane@example.com",
            "phone": "+1234567890",
            "_formatted": {"first_name": "<mark>Jane</mark>", "last_name": "Doe"},
        }
        base_url = "https://api.example.com"

        resource = create_contact_resource_from_search_hit(hit, base_url)

        assert resource.type == "contacts"
        assert resource.id == "456"
        assert resource.attributes.first_name == "Jane"
        assert resource.attributes.last_name == "Doe"
        assert resource.attributes.middle_name == "Marie"
        assert resource.attributes.nick_name == "Janie"
        # Datetime fields are parsed by Pydantic, so check they're not None
        assert resource.attributes.created_at is not None
        assert resource.attributes.updated_at is not None
        assert resource.links is not None
        assert resource.links.self == "https://api.example.com/api/contacts/456"
        assert resource.meta is not None
        assert resource.meta["highlighted"] == hit["_formatted"]
        assert resource.meta["search_metadata"]["tags"] == ["friend", "work"]
        assert resource.meta["search_metadata"]["email"] == "jane@example.com"
        assert resource.meta["search_metadata"]["phone"] == "+1234567890"

    def test_empty_first_name_defaults(self):
        """Test that empty first_name gets default value."""
        hit = {
            "id": 789,
            "first_name": "",  # Empty string
        }
        base_url = "https://api.example.com"

        resource = create_contact_resource_from_search_hit(hit, base_url)

        assert resource.attributes.first_name == ""  # Should preserve empty string

    def test_missing_optional_fields(self):
        """Test handling of missing optional fields."""
        hit = {
            "id": 999,
            "first_name": "Test",
            # Missing: last_name, middle_name, nick_name, etc.
        }
        base_url = "https://api.example.com"

        resource = create_contact_resource_from_search_hit(hit, base_url)

        assert resource.attributes.first_name == "Test"
        assert resource.attributes.last_name is None
        assert resource.attributes.middle_name is None
        assert resource.attributes.nick_name is None
        assert resource.attributes.created_at is None
        assert resource.attributes.updated_at is None
        assert resource.meta is not None
        assert resource.meta["search_metadata"]["tags"] == []
        assert resource.meta["search_metadata"]["email"] is None
        assert resource.meta["search_metadata"]["phone"] is None
