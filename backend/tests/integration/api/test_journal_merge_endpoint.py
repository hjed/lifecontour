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


@pytest.mark.asyncio
async def test_merge_journal_with_overrides(
    authenticated_client: AsyncClient,
    clean_database: None,
) -> None:
    """Test merging journals with explicit base and type data overrides."""
    # Create target journal with MOOD_RATING
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
                    "types": ["MOOD_RATING"],
                    "type_data": {
                        "MOOD_RATING": {
                            "mood_value": 3,
                            "energy_level": 5,
                        }
                    },
                },
            }
        },
    )
    assert target_res.status_code == 201, target_res.text
    target_id = int(target_res.json()["data"]["id"])

    # Create source journal with MOOD_RATING
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
                    "types": ["MOOD_RATING"],
                    "type_data": {
                        "MOOD_RATING": {
                            "mood_value": 8,
                            "energy_level": 8,
                        }
                    },
                },
            }
        },
    )
    assert source_res.status_code == 201, source_res.text
    source_id = int(source_res.json()["data"]["id"])

    # Merge source into target with overrides
    merge_res = await authenticated_client.post(
        f"/api/journals/{target_id}/merge",
        json={
            "data": {
                "type": "journal-merge",
                "attributes": {
                    "source_journal_id": source_id,
                    "overrides": {
                        "title": "Override Title",
                        "content": "Override Content",
                        "type_data": {
                            "MOOD_RATING": {
                                "mood_value": 8,  # Overriding with source's mood
                                # leaving energy_level out to test it defaults to target's value
                            }
                        },
                    },
                },
            }
        },
    )

    assert merge_res.status_code == 200, merge_res.text
    data = merge_res.json()["data"]["attributes"]

    # Assert base overrides
    assert data["title"] == "Override Title"
    assert data["content"] == "Override Content"

    # Assert type data overrides
    type_data = data.get("type_data", {})
    assert "mood_rating" in type_data
    # mood_value should be 8 from override
    assert type_data["mood_rating"]["mood_value"] == 8
    # energy_level should be 5 from target (since it was not overridden and target wins)
    assert type_data["mood_rating"]["energy_level"] == 5

    # Source should be deleted
    get_source_res = await authenticated_client.get(f"/api/journals/{source_id}")
    assert get_source_res.status_code == 404


@pytest.mark.integration
async def test_merge_journal_with_route(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
) -> None:
    """Test that routes are correctly moved from source to target journal during merge."""
    from core_shared.models.route import Route

    from app.core.journal.adapters.sql.route_repository import SqlRouteRepository

    # Create target journal
    target_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Target Journal",
                    "content": "Target content",
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

    # Create source journal
    source_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Source Journal",
                    "content": "Source content",
                    "event_date_range": {
                        "start": "2024-01-02T00:00:00Z",
                        "end": "2024-01-02T01:00:00Z",
                    },
                },
            }
        },
    )
    assert source_res.status_code == 201
    source_id = int(source_res.json()["data"]["id"])

    # Directly create a route associated with the source journal
    route_repo = SqlRouteRepository(async_connection)
    test_route = Route(
        journal_id=source_id,
        name="Test Route for Merge",
        description="This route should be moved to Target Journal.",
    )
    saved_route = await route_repo.save(test_route)
    assert saved_route.id is not None

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

    # Verify route ownership moved to target
    routes = await route_repo.find_by_journal_id(target_id)
    assert len(routes) == 1
    assert routes[0].id == saved_route.id
    assert routes[0].name == "Test Route for Merge"

    # Verify source doesn't have it anymore (although source is deleted)
    routes_source = await route_repo.find_by_journal_id(source_id)
    assert len(routes_source) == 0
