"""
Unit tests for MeiliSearch client configuration.

Tests the MeiliSearch client configuration and index settings.
"""

from app.infrastructure.search.meilisearch_client import CONTACTS_INDEX_SETTINGS


class TestMeiliSearchClientConfiguration:
    """Test cases for MeiliSearch client configuration."""

    def test_contacts_index_settings_includes_is_favourite_filterable(self):
        """Test that CONTACTS_INDEX_SETTINGS includes is_favourite as filterable attribute."""
        # Assert
        assert "filterableAttributes" in CONTACTS_INDEX_SETTINGS
        filterable_attributes = CONTACTS_INDEX_SETTINGS["filterableAttributes"]

        # Check that is_favourite is included in filterable attributes
        assert "is_favourite" in filterable_attributes

        # Verify other expected filterable attributes are still present
        expected_filterable = [
            "tags",
            "entity_type",
            "created_at",
            "updated_at",
            "is_favourite",
        ]
        for attr in expected_filterable:
            assert attr in filterable_attributes

    def test_contacts_index_settings_includes_is_favourite_displayed(self):
        """Test that CONTACTS_INDEX_SETTINGS includes is_favourite as displayed attribute."""
        # Assert
        assert "displayedAttributes" in CONTACTS_INDEX_SETTINGS
        displayed_attributes = CONTACTS_INDEX_SETTINGS["displayedAttributes"]

        # Check that is_favourite is included in displayed attributes
        assert "is_favourite" in displayed_attributes

        # Verify other expected displayed attributes are still present
        expected_displayed = [
            "id",
            "first_name",
            "last_name",
            "middle_name",
            "nick_name",
            "full_name",
            "email",
            "emails",
            "phone",
            "phones",
            "notes_content",
            "tags",
            "entity_type",
            "created_at",
            "updated_at",
            "is_favourite",
        ]
        for attr in expected_displayed:
            assert attr in displayed_attributes

    def test_contacts_index_settings_searchable_attributes_unchanged(self):
        """Test that searchable attributes remain unchanged (is_favourite should not be searchable)."""
        # Assert
        assert "searchableAttributes" in CONTACTS_INDEX_SETTINGS
        searchable_attributes = CONTACTS_INDEX_SETTINGS["searchableAttributes"]

        # is_favourite should NOT be in searchable attributes (it's for filtering, not searching)
        assert "is_favourite" not in searchable_attributes

        # Verify expected searchable attributes are present
        expected_searchable = [
            "first_name",
            "last_name",
            "middle_name",
            "nick_name",
            "full_name",
            "email",
            "emails",
            "phone",
            "phones",
            "notes_content",
        ]
        for attr in expected_searchable:
            assert attr in searchable_attributes

    def test_contacts_index_settings_sortable_attributes_unchanged(self):
        """Test that sortable attributes remain unchanged (is_favourite could be sortable but not required)."""
        # Assert
        assert "sortableAttributes" in CONTACTS_INDEX_SETTINGS
        sortable_attributes = CONTACTS_INDEX_SETTINGS["sortableAttributes"]

        # Verify expected sortable attributes are present
        expected_sortable = ["created_at", "updated_at", "last_name", "first_name"]
        for attr in expected_sortable:
            assert attr in sortable_attributes
