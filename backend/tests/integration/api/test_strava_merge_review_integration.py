"""Integration tests for Strava journal merge logic.

Tests the end-to-end flow of merging journals with Strava data:
1. Merge of Strava journals preserves fitness data and routes
2. Strava activity + Google Calendar event → verify cross-integration merge preserves data
3. Validates correct source-to-target data transfer and source deletion
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@pytest.mark.integration
async def test_merge_strava_journals_preserves_fitness_data(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """Merging two Strava-sourced journals preserves fitness data on the target.

    Product spec: On merge, fitness data should be preserved on the target journal
    via existing JournalMergeService._merge_type_data.
    """
    # Create target journal with fitness data
    target_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Morning Run - Part 1",
                    "content": "First leg of the run",
                    "event_date_range": {
                        "start": "2026-03-20T08:00:00Z",
                        "end": "2026-03-20T09:30:00Z",
                    },
                    "types": ["FITNESS"],
                    "type_data": {
                        "FITNESS": {
                            "distance": 5000,
                            "elevation_gain": 50,
                            "duration": 1800,
                            "calories": 300,
                        }
                    },
                },
            }
        },
    )
    assert target_res.status_code == 201, target_res.text
    target_id = int(target_res.json()["data"]["id"])

    # Create source journal with fitness data (second Strava activity)
    source_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Morning Run - Part 2",
                    "content": "Second leg of the run after restart",
                    "event_date_range": {
                        "start": "2026-03-20T10:00:00Z",
                        "end": "2026-03-20T11:00:00Z",
                    },
                    "types": ["FITNESS"],
                    "type_data": {
                        "FITNESS": {
                            "distance": 3000,
                            "elevation_gain": 30,
                            "duration": 1200,
                            "calories": 200,
                        }
                    },
                },
            }
        },
    )
    assert source_res.status_code == 201, source_res.text
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
    assert merge_res.status_code == 200, merge_res.text

    # Verify target journal still has fitness data
    target_detail = await authenticated_client.get(f"/api/journals/{target_id}")
    assert target_detail.status_code == 200
    data = target_detail.json()["data"]["attributes"]
    type_data = data.get("type_data", {})
    assert "fitness" in type_data, (
        f"Expected fitness type_data, got: {type_data.keys()}"
    )
    # Target's fitness data should be preserved (target wins by default)
    assert type_data["fitness"]["distance"] == 5000

    # Source should be deleted
    source_detail = await authenticated_client.get(f"/api/journals/{source_id}")
    assert source_detail.status_code == 404


@pytest.mark.integration
async def test_merge_strava_journal_with_route_preserved(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """Merging a Strava journal with a GPX route preserves the route on target.

    Product spec: GPX tracks (routes) should be preserved on the target journal
    via existing JournalMergeService._move_routes.
    """
    from core_shared.models.route import Route

    from app.core.journal.adapters.sql.route_repository import SqlRouteRepository

    # Create target journal (e.g., from Google Calendar)
    target_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Saturday Bushwalk",
                    "content": "Bushwalk with the group",
                    "event_date_range": {
                        "start": "2026-03-20T08:00:00Z",
                        "end": "2026-03-20T14:00:00Z",
                    },
                },
            }
        },
    )
    assert target_res.status_code == 201
    target_id = int(target_res.json()["data"]["id"])

    # Create source journal (Strava activity with route)
    source_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Saturday Bushwalk",
                    "content": "GPS tracked trail",
                    "event_date_range": {
                        "start": "2026-03-20T08:30:00Z",
                        "end": "2026-03-20T13:00:00Z",
                    },
                    "types": ["FITNESS"],
                    "type_data": {
                        "FITNESS": {
                            "distance": 15000,
                            "elevation_gain": 500,
                            "duration": 16200,
                        }
                    },
                },
            }
        },
    )
    assert source_res.status_code == 201
    source_id = int(source_res.json()["data"]["id"])

    # Create a route on the source journal (simulating GPX from Strava)
    route_repo = SqlRouteRepository(async_connection)
    gpx_xml = '<?xml version="1.0"?><gpx><trk><trkseg><trkpt lat="-33.8" lon="151.2"></trkpt></trkseg></trk></gpx>'
    test_route = Route(
        journal_id=source_id,
        name="Saturday Bushwalk Track",
        description="GPX track from Strava",
        gpx_data=gpx_xml,
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

    # Verify route was moved to target
    routes = await route_repo.find_by_journal_id(target_id)
    assert len(routes) == 1
    assert routes[0].name == "Saturday Bushwalk Track"
    assert routes[0].gpx_data == gpx_xml

    # Target should also have fitness data from source
    target_detail = await authenticated_client.get(f"/api/journals/{target_id}")
    assert target_detail.status_code == 200
    data = target_detail.json()["data"]["attributes"]
    type_data = data.get("type_data", {})
    assert "fitness" in type_data


@pytest.mark.integration
async def test_merge_cross_integration_google_and_strava(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """Merging a Google Calendar journal with a Strava journal preserves both external links.

    Product spec: When merging a Strava activity with a Google Calendar EVENT:
    - The Google Calendar external event link is preserved
    - The Strava reference (via strava_activity_id) is preserved in fitness data
    """
    from uuid import uuid4

    # Create a calendar (for external link)
    calendar_id = uuid4()
    await async_connection.execute(
        text("""
            INSERT INTO calendars (id, user_id, name, color)
            VALUES (:id, :user_id, :name, :color)
        """),
        {
            "id": calendar_id,
            "user_id": "test-user-123",
            "name": "Google Calendar",
            "color": "#3B82F6",
        },
    )

    # Create target journal (Google Calendar event - without EVENT type_data
    # since the API validator requires calendar_id for EVENT types)
    target_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Saturday Bushwalk",
                    "content": "Bushwalk with the hiking group",
                    "event_date_range": {
                        "start": "2026-03-20T08:00:00Z",
                        "end": "2026-03-20T16:00:00Z",
                    },
                },
            }
        },
    )
    assert target_res.status_code == 201, target_res.text
    target_id = int(target_res.json()["data"]["id"])

    # Add Google Calendar external link to target
    await async_connection.execute(
        text("""
            INSERT INTO journal_external_event_links
                (journal_id, calendar_id, external_event_id, sync_capability, sync_status)
            VALUES (:jid, :cid, :eid, 'bidirectional', 'synced')
        """),
        {
            "jid": target_id,
            "cid": calendar_id,
            "eid": "google-event-abc123",
        },
    )

    # Create source journal (Strava activity)
    source_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Saturday Bushwalk",
                    "content": "GPS tracked trail",
                    "event_date_range": {
                        "start": "2026-03-20T08:30:00Z",
                        "end": "2026-03-20T14:00:00Z",
                    },
                    "types": ["FITNESS", "BUSHWALKING"],
                    "type_data": {
                        "FITNESS": {
                            "distance": 15000,
                            "elevation_gain": 500,
                            "duration": 16200,
                            "strava_activity_id": "strava-99999",
                        },
                        "BUSHWALKING": {
                            "trail_name": "Blue Mountains Track",
                        },
                    },
                },
            }
        },
    )
    assert source_res.status_code == 201, source_res.text
    source_id = int(source_res.json()["data"]["id"])

    # Merge source into target (simulating user resolving via review queue)
    merge_res = await authenticated_client.post(
        f"/api/journals/{target_id}/merge",
        json={
            "data": {
                "type": "journal-merge",
                "attributes": {"source_journal_id": source_id},
            }
        },
    )
    assert merge_res.status_code == 200, merge_res.text

    # Verify target has fitness data from Strava source
    target_detail = await authenticated_client.get(f"/api/journals/{target_id}")
    assert target_detail.status_code == 200
    data = target_detail.json()["data"]["attributes"]
    type_data = data.get("type_data", {})
    assert "fitness" in type_data
    assert type_data["fitness"]["distance"] == 15000
    assert type_data["fitness"]["strava_activity_id"] == "strava-99999"

    # Verify Google Calendar external link is preserved
    link_result = await async_connection.execute(
        text("""
            SELECT external_event_id
            FROM journal_external_event_links
            WHERE journal_id = :jid AND calendar_id = :cid
        """),
        {"jid": target_id, "cid": calendar_id},
    )
    link_row = link_result.fetchone()
    assert link_row is not None
    assert link_row[0] == "google-event-abc123"

    # Source should be deleted
    source_detail = await authenticated_client.get(f"/api/journals/{source_id}")
    assert source_detail.status_code == 404
