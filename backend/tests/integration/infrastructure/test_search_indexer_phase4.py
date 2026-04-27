"""
Integration tests for Phase 4 of search indexer.
Tests that `_fetch_complete_contact_data` captures important dates, summaries, journals, and activities.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.search.search_indexer import SearchIndexer

pytestmark = pytest.mark.asyncio


async def test_fetch_complete_contact_data_captures_signals(
    async_connection: AsyncConnection,
) -> None:
    """Test that search indexer captures all required ranking signals."""

    # Setup test data
    # 1. Create contact
    contact_id = 1
    await async_connection.execute(
        text("""
            INSERT INTO contacts (id, first_name, created_at, updated_at)
            VALUES (:id, 'Signal Test Contact', :now, :now)
        """),
        {"id": contact_id, "now": datetime.now(UTC)},
    )

    # 2. Add summary
    await async_connection.execute(
        text("""
            INSERT INTO contact_summaries (contact_id, summary_text, is_disabled, created_at, updated_at)
            VALUES (:id, 'This is a test summary.', false, :now, :now)
        """),
        {"id": contact_id, "now": datetime.now(UTC)},
    )

    # 3. Add disabled summary for another contact (to test robustness)
    contact_id2 = 2
    await async_connection.execute(
        text("""
            INSERT INTO contacts (id, first_name, created_at, updated_at)
            VALUES (:id, 'Disabled Summary Contact', :now, :now)
        """),
        {"id": contact_id2, "now": datetime.now(UTC)},
    )
    await async_connection.execute(
        text("""
            INSERT INTO contact_summaries (contact_id, summary_text, is_disabled, created_at, updated_at)
            VALUES (:id, 'Hidden summary.', true, :now, :now)
        """),
        {"id": contact_id2, "now": datetime.now(UTC)},
    )

    # 4. Add important date
    await async_connection.execute(
        text("""
            INSERT INTO contact_important_dates (contact_id, date_type, precision, year, month, day, created_at, updated_at)
            VALUES (:id, 'birthday', 'day_month', null, 5, 15, :now, :now)
        """),
        {"id": contact_id, "now": datetime.now(UTC)},
    )

    # 5. Add recent journal
    journal_id = 1
    recent_date = datetime.now(UTC) - timedelta(days=5)
    await async_connection.execute(
        text("""
            INSERT INTO journals (id, user_id, title, content, event_date_range_start, event_date_range_end, created_at, updated_at)
            VALUES (:id, 'user1', 'Recent Meeting', 'Notes', :created_at, :created_at, :created_at, :now)
        """),
        {"id": journal_id, "created_at": recent_date, "now": datetime.now(UTC)},
    )
    await async_connection.execute(
        text(
            "INSERT INTO journal_contact_relationships (journal_id, contact_id, relationship_type) VALUES (:j_id, :c_id, 'MENTION')"
        ),
        {"j_id": journal_id, "c_id": contact_id},
    )

    # 6. Add old journal
    journal_id_old = 2
    old_date = datetime.now(UTC) - timedelta(days=40)
    await async_connection.execute(
        text("""
            INSERT INTO journals (id, user_id, title, content, event_date_range_start, event_date_range_end, created_at, updated_at)
            VALUES (:id, 'user1', 'Old Meeting', 'Notes', :created_at, :created_at, :created_at, :now)
        """),
        {"id": journal_id_old, "created_at": old_date, "now": datetime.now(UTC)},
    )
    await async_connection.execute(
        text(
            "INSERT INTO journal_contact_relationships (journal_id, contact_id, relationship_type) VALUES (:j_id, :c_id, 'MENTION')"
        ),
        {"j_id": journal_id_old, "c_id": contact_id},
    )

    # 7. Add field history
    history_date = datetime.now(UTC) - timedelta(days=10)
    await async_connection.execute(
        text("""
            INSERT INTO contact_field_history (entity_id, entity_type, field_name, new_value, created_at)
            VALUES (:id, 'contact', 'first_name', 'new_name', :created_at)
        """),
        {"id": contact_id, "created_at": history_date},
    )

    # Test execution
    indexer = SearchIndexer(db_connection=async_connection)

    data1 = await indexer._fetch_complete_contact_data(contact_id)
    assert data1 is not None

    # Verify summary
    assert data1["summary_text"] == "This is a test summary."
    assert data1["has_summary"] is True

    # Verify important dates
    assert "Birthday (May 15)" in data1["important_dates"]

    # Verify journal mentions and counts
    assert "Recent Meeting" in data1["journal_mentions"]
    assert "Old Meeting" in data1["journal_mentions"]
    assert data1["journal_count_30d"] == 1

    # Verify activity counts
    assert data1["activity_count_30d"] == 1

    # Test disabled summary
    data2 = await indexer._fetch_complete_contact_data(contact_id2)
    assert data2 is not None
    assert data2["summary_text"] is None
    assert data2["has_summary"] is False
