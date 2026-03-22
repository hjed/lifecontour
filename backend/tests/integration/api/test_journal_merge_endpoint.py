"""Integration tests for the journal merge endpoint."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection


@pytest.mark.asyncio
async def test_merge_journal_endpoint_success(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """Test successful journal merge."""
    # Create journals
    target_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Target Title",
                    "content": "Target Content",
                    "event_date_range": {
                        "start": "2024-01-01T00:00:00Z",
                        "end": "2024-01-01T01:00:00Z",
                    },
                },
            }
        },
    )
    assert target_res.status_code == 201
    target_id = int(target_res.json()["data"]["id"])

    source_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Target Title",
                    "content": "Source Content",
                    "event_date_range": {
                        "start": "2024-01-01T00:00:00Z",
                        "end": "2024-01-01T01:00:00Z",
                    },
                },
            }
        },
    )
    assert source_res.status_code == 201
    source_id = int(source_res.json()["data"]["id"])

    # Merge source into target
    merge_res = await authenticated_client.post(
        f"/api/journals/{target_id}/merge",
        json={
            "data": {
                "type": "journal-merge",
                "attributes": {"source_journal_id": source_id},
            }
        },
    )

    assert merge_res.status_code == 200
    data = merge_res.json()["data"]["attributes"]
    assert data["title"] == "Target Title"
    assert data["content"] == "Target Content\n\n---\n\nSource Content"

    # Source should be deleted
    get_source_res = await authenticated_client.get(f"/api/journals/{source_id}")
    assert get_source_res.status_code == 404


@pytest.mark.asyncio
async def test_merge_journal_different_titles(
    authenticated_client: AsyncClient,
    clean_database: None,
) -> None:
    """Test merging journals with different titles succeeds and targets title wins."""
    # Create journals with conflicting titles
    target_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Target Title",
                    "content": "Target Content",
                    "event_date_range": {
                        "start": "2024-01-01T00:00:00Z",
                        "end": "2024-01-01T01:00:00Z",
                    },
                },
            }
        },
    )
    target_id = int(target_res.json()["data"]["id"])

    source_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Source Title",
                    "content": "Source Content",
                    "event_date_range": {
                        "start": "2024-01-01T00:00:00Z",
                        "end": "2024-01-01T01:00:00Z",
                    },
                },
            }
        },
    )
    source_id = int(source_res.json()["data"]["id"])

    # Merge source into target
    merge_res = await authenticated_client.post(
        f"/api/journals/{target_id}/merge",
        json={
            "data": {
                "type": "journal-merge",
                "attributes": {"source_journal_id": source_id},
            }
        },
    )

    assert merge_res.status_code == 200
    data = merge_res.json()["data"]["attributes"]
    assert data["title"] == "Target Title"
    assert data["content"] == "Target Content\n\n---\n\nSource Content"
