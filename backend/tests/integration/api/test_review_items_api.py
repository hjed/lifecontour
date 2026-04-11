import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.config import Settings

# Use the same fixture setup as test_journal_api_filters.py
# The authenticated_client fixture from conftest.py handles DB changes via savepoints

pytestmark = pytest.mark.asyncio


async def test_list_review_items_empty(authenticated_client):
    """Test getting review items when queue is empty."""
    response = await authenticated_client.get("/api/journals/review-items")
    assert response.status_code == 200
    data = response.json()
    assert data["data"] == []
    assert data["meta"]["total_count"] == 0


async def test_test_endpoint_respects_feature_flag(
    authenticated_client, test_settings: Settings
):
    """Test that the test-only create endpoint is correctly gated."""
    # Ensure it's disabled
    test_settings.enable_test_review_items = False

    response = await authenticated_client.post(
        "/api/journals/review-items",
        json={
            "data": {
                "type": "review-items",
                "attributes": {
                    "source_journal_id": 1,
                    "candidate_journal_id": 2,
                    "reason": "duplicate_journal",
                    "confidence_score": 0.95,
                },
            }
        },
    )
    assert response.status_code == 404


async def test_create_and_list_review_items(
    authenticated_client,
    test_settings: Settings,
    async_connection: AsyncConnection,
):
    """Test full flow: enable test endpoint, create an item, and list it."""
    # Enable test endpoint
    test_settings.enable_test_review_items = True

    # 1. Create source and candidate journals directly to ensure they exist
    from datetime import UTC, datetime

    now = datetime.now(UTC)

    # Create source journal
    result1 = await async_connection.execute(
        text("""
        INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
        VALUES ('test-user-123', 'Source Journal', 'Source content', :now, :now)
        RETURNING id
        """),
        {"now": now},
    )
    row1 = result1.fetchone()
    assert row1 is not None
    source_id = row1[0]

    # Create candidate journal
    result2 = await async_connection.execute(
        text("""
        INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
        VALUES ('test-user-123', 'Candidate Journal', 'Candidate content', :now, :now)
        RETURNING id
        """),
        {"now": now},
    )
    row2 = result2.fetchone()
    assert row2 is not None
    candidate_id = row2[0]

    # 2. Add review item via API
    response = await authenticated_client.post(
        "/api/journals/review-items",
        json={
            "data": {
                "type": "review-items",
                "attributes": {
                    "source_journal_id": source_id,
                    "candidate_journal_id": candidate_id,
                    "reason": "duplicate_journal",
                    "confidence_score": 0.85,
                    "details": {"similarity": 0.85},
                },
            }
        },
    )
    assert response.status_code == 201
    created_id = response.json()["data"]["id"]

    # 3. List review items
    list_resp = await authenticated_client.get("/api/journals/review-items")
    assert list_resp.status_code == 200

    data = list_resp.json()
    assert data["meta"]["total_count"] == 1
    items = data["data"]
    assert len(items) == 1

    item = items[0]
    assert item["id"] == str(created_id)
    attrs = item["attributes"]
    assert attrs["reason"] == "duplicate_journal"
    assert attrs["confidence_score"] == pytest.approx(0.85)
    assert attrs["status"] == "pending"
    assert attrs["details"] == {"similarity": 0.85}

    # Verify embedded journal info
    assert attrs["source_journal"]["id"] == source_id
    assert attrs["source_journal"]["title"] == "Source Journal"
    assert attrs["candidate_journal"]["id"] == candidate_id
    assert attrs["candidate_journal"]["title"] == "Candidate Journal"

    # 4. Check journal list indicator
    list_journal_resp = await authenticated_client.get("/api/journals")
    assert list_journal_resp.status_code == 200

    journals = list_journal_resp.json()["data"]
    # Source journal should have has_pending_reviews = True
    # Let's find it in the list
    for j in journals:
        if j["id"] == str(source_id):
            assert j["attributes"]["has_pending_reviews"] is True

    # 5. Check journal detail indicator and embedded items
    detail_resp = await authenticated_client.get(f"/api/journals/{source_id}")
    assert detail_resp.status_code == 200

    detail_attrs = detail_resp.json()["data"]["attributes"]
    assert detail_attrs["has_pending_reviews"] is True
    assert len(detail_attrs["review_items"]) == 1

    review_suggestion = detail_attrs["review_items"][0]
    assert review_suggestion["id"] == int(created_id)
    assert review_suggestion["reason"] == "duplicate_journal"
    assert review_suggestion["candidate_journal_id"] == candidate_id
    assert review_suggestion["candidate_journal_title"] == "Candidate Journal"


async def test_dismiss_review_item(
    authenticated_client,
    test_settings: Settings,
    async_connection: AsyncConnection,
):
    """Test dismissing a review item via API."""
    test_settings.enable_test_review_items = True

    from datetime import UTC, datetime

    now = datetime.now(UTC)

    result = await async_connection.execute(
        text("""
        INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
        VALUES ('test-user-123', 'Source', '', :now, :now),
               ('test-user-123', 'Candidate', '', :now, :now)
        RETURNING id
        """),
        {"now": now},
    )
    rows = result.fetchall()
    source_id = rows[0][0]
    candidate_id = rows[1][0]

    response = await authenticated_client.post(
        "/api/journals/review-items",
        json={
            "data": {
                "type": "review-items",
                "attributes": {
                    "source_journal_id": source_id,
                    "candidate_journal_id": candidate_id,
                    "reason": "duplicate_journal",
                    "confidence_score": 0.85,
                },
            }
        },
    )
    assert response.status_code == 201
    created_id = response.json()["data"]["id"]

    dismiss_resp = await authenticated_client.post(
        f"/api/journals/review-items/{created_id}/dismiss"
    )
    assert dismiss_resp.status_code == 200

    dismissed_data = dismiss_resp.json()["data"]["attributes"]
    assert dismissed_data["status"] == "dismissed"

    # Should no longer appear in the pending list
    list_resp = await authenticated_client.get("/api/journals/review-items")
    assert list_resp.status_code == 200
    assert list_resp.json()["meta"]["total_count"] == 0
