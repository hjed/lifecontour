#!/usr/bin/env python3
"""
Test script to verify enhanced search indexing functionality.

Tests that the SearchIndexer properly fetches complete contact data
and creates comprehensive search documents.
"""

import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


async def test_enhanced_contact_indexing() -> bool:
    """Test that SearchIndexer creates comprehensive contact documents."""
    print("Testing enhanced contact indexing...")

    try:
        from app.infrastructure.events.outbox_repository import OutboxEvent
        from app.infrastructure.search.search_indexer import SearchIndexer

        # Create mock database connection with realistic data
        mock_conn = AsyncMock()

        # Mock contact data query result
        contact_row = MagicMock()
        contact_row.id = 42
        contact_row.first_name = "John"
        contact_row.last_name = "Doe"
        contact_row.middle_name = "Michael"
        contact_row.nick_name = "Johnny"
        contact_row.created_at = datetime(2024, 1, 1, 12, 0, 0)
        contact_row.updated_at = datetime(2024, 1, 1, 12, 0, 0)

        # Mock methods data (email and phone)
        method_rows = [
            MagicMock(
                method_type="email",
                value="john@example.com",
                label="work",
                is_primary=True,
            ),
            MagicMock(
                method_type="email",
                value="johnny@personal.com",
                label="personal",
                is_primary=False,
            ),
            MagicMock(
                method_type="phone",
                value="+1234567890",
                label="mobile",
                is_primary=True,
            ),
            MagicMock(
                method_type="phone", value="+1987654321", label="work", is_primary=False
            ),
        ]

        # Mock notes data
        note_rows = [
            MagicMock(content="Important client meeting scheduled"),
            MagicMock(content="Prefers email communication"),
        ]

        # Mock tags data
        tag_rows = [
            MagicMock(name="VIP"),
            MagicMock(name="Customer"),
            MagicMock(name="Tech"),
        ]

        # Setup mock execute responses
        mock_results = [
            # Contact query result
            MagicMock(fetchone=MagicMock(return_value=contact_row)),
            # Methods query result
            MagicMock(fetchall=MagicMock(return_value=method_rows)),
            # Notes query result
            MagicMock(fetchall=MagicMock(return_value=note_rows)),
            # Tags query result
            MagicMock(fetchall=MagicMock(return_value=tag_rows)),
        ]

        mock_conn.execute.side_effect = mock_results

        # Create mock MeiliSearch client
        mock_client = MagicMock()
        mock_index = MagicMock()
        mock_client.index.return_value = mock_index
        mock_index.get_stats.return_value = {"numberOfDocuments": 0}
        mock_task = MagicMock()
        mock_task.task_uid = "test-task"
        mock_index.add_documents.return_value = mock_task

        # Create SearchIndexer with mocked dependencies
        with (
            patch(
                "app.infrastructure.search.search_indexer.get_meilisearch_client",
                return_value=mock_client,
            ),
            patch(
                "app.infrastructure.search.search_indexer.get_index_name",
                return_value="test_contacts",
            ),
        ):
            indexer = SearchIndexer(db_connection=mock_conn)

            # Create test event
            event = OutboxEvent(
                id=1,
                event_id="test-contact-created",
                event_type="ContactCreated",
                aggregate_id=42,
                event_data={"contact_id": 42, "first_name": "John", "last_name": "Doe"},
                occurred_at=datetime(2024, 1, 1, 12, 0, 0),
                retry_count=0,
                created_at=datetime(2024, 1, 1, 12, 0, 0),
            )

            # Process the event
            await indexer.process_event(event)

        # Verify database queries were made
        assert mock_conn.execute.call_count == 4, (
            f"Expected 4 DB queries, got {mock_conn.execute.call_count}"
        )

        # Verify MeiliSearch indexing was called
        mock_index.add_documents.assert_called_once()

        # Get the indexed document
        indexed_docs = mock_index.add_documents.call_args[0][0]
        assert len(indexed_docs) == 1

        doc = indexed_docs[0]

        # Verify comprehensive document structure
        expected_fields = {
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
        }

        actual_fields = set(doc.keys())
        missing_fields = expected_fields - actual_fields
        assert not missing_fields, f"Missing fields in document: {missing_fields}"

        # Verify field values
        assert doc["id"] == 42
        assert doc["first_name"] == "John"
        assert doc["last_name"] == "Doe"
        assert doc["middle_name"] == "Michael"
        assert doc["nick_name"] == "Johnny"
        assert doc["full_name"] == "John Doe"
        assert doc["email"] == "john@example.com"  # Primary email
        assert doc["emails"] == ["john@example.com", "johnny@personal.com"]
        assert doc["phone"] == "+1234567890"  # Primary phone
        assert doc["phones"] == ["+1234567890", "+1987654321"]
        assert "Important client meeting" in doc["notes_content"]
        assert "Prefers email communication" in doc["notes_content"]
        assert doc["tags"] == ["VIP", "Customer", "Tech"]
        assert doc["entity_type"] == "contact"

        print("✓ Enhanced contact indexing works correctly")
        print(f"✓ Document contains {len(doc)} fields")
        print(f"✓ Searchable emails: {doc['emails']}")
        print(f"✓ Searchable phones: {doc['phones']}")
        print(f"✓ Notes content: {len(doc['notes_content'])} characters")
        print(f"✓ Tags: {doc['tags']}")

        return True

    except Exception as e:  # noqa: BLE001
        print(f"✗ Enhanced indexing test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_search_index_settings() -> bool:
    """Test that search index settings include all necessary fields."""
    print("\nTesting search index settings...")

    try:
        from app.infrastructure.search.meilisearch_client import CONTACTS_INDEX_SETTINGS

        # Verify searchable attributes include all contact fields
        searchable = CONTACTS_INDEX_SETTINGS["searchableAttributes"]
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

        for field in expected_searchable:
            assert field in searchable, f"Missing searchable field: {field}"

        # Verify filterable attributes
        filterable = CONTACTS_INDEX_SETTINGS["filterableAttributes"]
        expected_filterable = ["tags", "entity_type", "created_at", "updated_at"]

        for field in expected_filterable:
            assert field in filterable, f"Missing filterable field: {field}"

        # Verify displayed attributes include comprehensive contact data
        displayed = CONTACTS_INDEX_SETTINGS["displayedAttributes"]
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
        ]

        for field in expected_displayed:
            assert field in displayed, f"Missing displayed field: {field}"

        print("✓ Search index settings are comprehensive")
        print(f"✓ {len(searchable)} searchable attributes")
        print(f"✓ {len(filterable)} filterable attributes")
        print(f"✓ {len(displayed)} displayed attributes")

        return True

    except Exception as e:  # noqa: BLE001
        print(f"✗ Index settings test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main() -> None:
    """Run all enhanced search tests."""
    print("Running enhanced search functionality tests...\n")

    # Import patch here to avoid issues
    global patch
    from unittest.mock import patch

    success = True
    success &= await test_enhanced_contact_indexing()
    success &= await test_search_index_settings()

    if success:
        print("\n🎉 All enhanced search tests passed!")
        print("\nThe search indexer now creates comprehensive documents with:")
        print("  • Complete contact information (names, emails, phones)")
        print("  • Searchable notes content")
        print("  • Filterable tags")
        print("  • Primary and secondary contact methods")
        print("  • Proper MeiliSearch field configuration")
    else:
        print("\n❌ Some enhanced search tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
