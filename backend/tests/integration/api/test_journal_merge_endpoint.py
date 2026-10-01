"""Integration tests for the journal merge endpoint."""

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.contact_seeding import seed_contact
from tests.integration.series_merge_seeding import (
    add_to_series,
    member_ids,
    seed_member,
    seed_series,
)
from tests.integration.tasks.task_seeding import (
    USER_ID,
    create_journal,
    create_task,
    task_events,
)


@pytest.mark.asyncio
async def test_merge_journal_endpoint_repoints_an_anchored_task(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    task_anchors: tuple[int, int],
) -> None:
    """Merging a journal a task is anchored to succeeds over REST.

    The anchors are ``ON DELETE RESTRICT``, so before the re-point this request
    answered with a raw integrity error. It is asserted at the endpoint rather
    than only at the service because the service reaches its task repository
    through the container, and only a real request proves that wiring.
    """
    creating_id, due_id = task_anchors

    target_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Survivor",
                    "content": "",
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

    task_res = await authenticated_client.post(
        f"/api/journals/{creating_id}/tasks",
        json={
            "data": {
                "type": "tasks",
                "attributes": {"text": "print the permit", "due_journal_id": due_id},
            }
        },
    )
    assert task_res.status_code == 201
    task_id = int(task_res.json()["data"]["id"])

    merge_res = await authenticated_client.post(
        f"/api/journals/{target_id}/merge",
        json={
            "data": {
                "type": "journal-merge",
                "attributes": {"source_journal_id": creating_id},
            }
        },
    )

    assert merge_res.status_code == 200
    anchors = await async_connection.execute(
        text(
            "SELECT creating_journal_id, due_journal_id, status "
            "FROM tasks WHERE id = :task_id"
        ),
        {"task_id": task_id},
    )
    row = anchors.fetchone()
    assert row is not None
    assert row.creating_journal_id == target_id
    assert row.due_journal_id == due_id
    assert row.status == "not_done"


@pytest.mark.asyncio
async def test_merge_journal_endpoint_records_the_move_on_the_task(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    task_anchors: tuple[int, int],
) -> None:
    """The task the merge moved says so, in the browser's name.

    Asserted at the endpoint rather than only at the service for the reason the
    re-point itself is: the REST path resolves the merge and the tasks domain's
    merge service out of the container, and the MCP tool builds both by hand, so
    neither is evidence for the other. What only this test can catch is a
    container that wires the merge to something which moves the links without
    announcing them — exactly the arrangement that shipped before this phase.

    ``ui`` is the whole point of the provenance thread. Before it, every merge's
    task events would have read ``system``, telling a user that a change they
    made in the browser was made by a background job.
    """
    creating_id, due_id = task_anchors

    target_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Survivor",
                    "content": "",
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

    task_res = await authenticated_client.post(
        f"/api/journals/{creating_id}/tasks",
        json={
            "data": {
                "type": "tasks",
                "attributes": {"text": "print the permit", "due_journal_id": due_id},
            }
        },
    )
    assert task_res.status_code == 201
    task_id = int(task_res.json()["data"]["id"])

    merge_res = await authenticated_client.post(
        f"/api/journals/{target_id}/merge",
        json={
            "data": {
                "type": "journal-merge",
                "attributes": {"source_journal_id": creating_id},
            }
        },
    )
    assert merge_res.status_code == 200

    repointed = [
        event
        for event in await task_events(async_connection, task_id=task_id)
        if event.event_type == "TaskJournalLinksRepointed"
    ]
    assert len(repointed) == 1
    assert repointed[0].payload["source"] == "ui"
    assert repointed[0].payload["changed_by"] == "ui"
    assert repointed[0].payload["changed_fields"] == {
        "creating_journal_id": [creating_id, target_id]
    }


@pytest.mark.asyncio
async def test_auto_merge_endpoint_records_the_move_on_the_task(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    journal_repository: Any,
    task_anchors: tuple[int, int],
) -> None:
    """The third merge surface, and the one the phase entry does not name.

    ``auto_merge_review_items`` merges every conflict-free pair in the review
    queue in **one** unit of work, so it is the only caller that can re-point the
    same task twice — which is why the event id names the absorbed journal — and
    the only one where "who did this?" is arguable. It is not arguable: *auto*
    describes how the pairs were chosen, not who chose to merge them, and a
    person pressed this button. Without the thread these merges would be the one
    kind that files a user's own task changes under the system.

    The two journals are built with an identical title, content and date range
    because that is what "conflict-free" means here — a fixed ``start`` rather
    than the clock, since two journals seeded a microsecond apart have different
    ranges and would be skipped as conflicting, leaving a test that passes while
    merging nothing.
    """
    _, due_id = task_anchors
    matched_start = datetime(2024, 6, 1, tzinfo=UTC)
    absorbed_id = await create_journal(
        journal_repository, title="The same outing", start=matched_start
    )
    survivor_id = await create_journal(
        journal_repository, title="The same outing", start=matched_start
    )
    task_id = await create_task(
        async_connection,
        creating_journal_id=absorbed_id,
        due_journal_id=due_id,
    )
    await async_connection.execute(
        text("""
            INSERT INTO journal_review_items (
                user_id, source_journal_id, candidate_journal_id,
                reason, confidence_score, status
            ) VALUES (
                :user_id, :source_id, :candidate_id,
                'duplicate_journal', 0.9, 'pending'
            )
        """),
        {"user_id": USER_ID, "source_id": absorbed_id, "candidate_id": survivor_id},
    )

    response = await authenticated_client.post("/api/journals/review-items/auto-merge")

    assert response.status_code == 200
    assert response.json()["data"]["attributes"]["merged_count"] == 1
    repointed = [
        event
        for event in await task_events(async_connection, task_id=task_id)
        if event.event_type == "TaskJournalLinksRepointed"
    ]
    assert len(repointed) == 1
    assert repointed[0].payload["source"] == "ui"
    assert repointed[0].payload["changed_by"] == "ui"
    assert repointed[0].payload["changed_fields"] == {
        "creating_journal_id": [absorbed_id, survivor_id]
    }


@pytest.mark.asyncio
async def test_merge_journal_endpoint_reports_survivor_hierarchy(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """The merge response describes where the survivor sits in the hierarchy.

    A merge leaves the target's own parent alone and adopts the source's
    children, so a response carrying neither reads as though the merge
    orphaned the survivor and dropped the children it just gained.
    """
    parent_id = await _create_journal(authenticated_client, "Parent Journal", "01")
    target_id = await _create_journal(
        authenticated_client, "Child Target", "01", parent_id=parent_id
    )
    source_id = await _create_journal(authenticated_client, "Source Journal", "01")
    adopted_id = await _create_journal(
        authenticated_client, "Adopted Child", "01", parent_id=source_id
    )

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
    attributes = merge_res.json()["data"]["attributes"]

    # Summary ids are strings, as JSON:API resource identifiers are everywhere
    # else in this API.
    assert attributes["parent_id"] == parent_id
    assert attributes["parent"] is not None
    assert attributes["parent"]["id"] == str(parent_id)
    assert attributes["parent"]["title"] == "Parent Journal"
    assert attributes["depth"] == 2

    # The count reports the child adopted from the source; the children
    # themselves are summarised (with their types) by the detail route.
    assert attributes["children_count"] == 1

    detail_res = await authenticated_client.get(f"/api/journals/{target_id}")
    assert detail_res.status_code == 200, detail_res.text
    detail_attributes = detail_res.json()["data"]["attributes"]
    assert [child["id"] for child in detail_attributes["children"]] == [str(adopted_id)]


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
async def test_merge_applies_type_data_override_for_a_source_only_type(
    authenticated_client: AsyncClient,
    clean_database: None,
) -> None:
    """An override lands even when only the source has a row for that type.

    The target carries no MOOD_RATING, so the merge moves the source's row
    wholesale — the branch that used to ignore ``type_data`` entirely.
    """
    target_id = await _create_journal(authenticated_client, "Target Title", "01")
    source_id = await _create_journal(
        authenticated_client,
        "Source Title",
        "01",
        types=["MOOD_RATING"],
        type_data={"MOOD_RATING": {"mood_value": 8, "energy_level": 8}},
    )

    merge_res = await authenticated_client.post(
        f"/api/journals/{target_id}/merge",
        json={
            "data": {
                "type": "journal-merge",
                "attributes": {
                    "source_journal_id": source_id,
                    "overrides": {"type_data": {"MOOD_RATING": {"mood_value": 3}}},
                },
            }
        },
    )

    assert merge_res.status_code == 200, merge_res.text
    mood = merge_res.json()["data"]["attributes"]["type_data"]["mood_rating"]

    # The override wins over the value the moved row carried.
    assert mood["mood_value"] == 3
    # Everything the caller did not override rides along on the moved row.
    assert mood["energy_level"] == 8


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


@pytest.mark.integration
async def test_merge_journals_with_external_links_to_same_calendar(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
) -> None:
    """Test merging journals when both have external event links to the same calendar.

    Reproduces the production IntegrityError on journal_external_event_links_pkey
    when source and target both link to the same calendar_id with different
    external_event_id values.
    """
    from uuid import uuid4

    from sqlalchemy import text

    # 1. Create a calendar
    calendar_id = uuid4()
    await async_connection.execute(
        text("""
            INSERT INTO calendars (id, user_id, name, color)
            VALUES (:id, :user_id, :name, :color)
        """),
        {
            "id": calendar_id,
            "user_id": "test-user-123",
            "name": "Shared Calendar",
            "color": "#3B82F6",
        },
    )

    # 2. Create target and source journals via API
    target_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Target with Link",
                    "content": "Target content",
                    "event_date_range": {
                        "start": "2024-06-01T10:00:00Z",
                        "end": "2024-06-01T11:00:00Z",
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
                    "title": "Source with Link",
                    "content": "Source content",
                    "event_date_range": {
                        "start": "2024-06-01T10:00:00Z",
                        "end": "2024-06-01T11:00:00Z",
                    },
                },
            }
        },
    )
    assert source_res.status_code == 201
    source_id = int(source_res.json()["data"]["id"])

    # 3. Insert external event links for both journals pointing to the same calendar
    await async_connection.execute(
        text("""
            INSERT INTO journal_external_event_links
                (journal_id, calendar_id, external_event_id, sync_capability, sync_status)
            VALUES (:jid, :cid, :eid, 'bidirectional', 'synced')
        """),
        {
            "jid": target_id,
            "cid": calendar_id,
            "eid": "target-google-event-abc",
        },
    )
    await async_connection.execute(
        text("""
            INSERT INTO journal_external_event_links
                (journal_id, calendar_id, external_event_id, sync_capability, sync_status)
            VALUES (:jid, :cid, :eid, 'bidirectional', 'synced')
        """),
        {
            "jid": source_id,
            "cid": calendar_id,
            "eid": "source-google-event-xyz",
        },
    )

    # 4. Merge — this must not raise an IntegrityError
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

    # 5. Verify target's original link was kept (target wins)
    result = await async_connection.execute(
        text("""
            SELECT external_event_id
            FROM journal_external_event_links
            WHERE journal_id = :jid AND calendar_id = :cid
        """),
        {"jid": target_id, "cid": calendar_id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "target-google-event-abc"

    # 6. Verify source link was not duplicated
    all_links = await async_connection.execute(
        text("""
            SELECT COUNT(*) FROM journal_external_event_links
            WHERE journal_id = :jid
        """),
        {"jid": target_id},
    )
    count_row = all_links.fetchone()
    assert count_row is not None
    assert count_row[0] == 1


@pytest.mark.integration
async def test_merge_journals_moves_source_only_external_link(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
) -> None:
    """Test merging when only the source has an external event link.

    Verifies the link is moved to the target without violating the unique
    partial index on (calendar_id, external_event_id).
    """
    from uuid import uuid4

    from sqlalchemy import text

    # 1. Create a calendar
    calendar_id = uuid4()
    await async_connection.execute(
        text("""
            INSERT INTO calendars (id, user_id, name, color)
            VALUES (:id, :user_id, :name, :color)
        """),
        {
            "id": calendar_id,
            "user_id": "test-user-123",
            "name": "Source-Only Calendar",
            "color": "#3B82F6",
        },
    )

    # 2. Create target and source journals
    target_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Target No Link",
                    "content": "Target content",
                    "event_date_range": {
                        "start": "2024-07-01T10:00:00Z",
                        "end": "2024-07-01T11:00:00Z",
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
                    "title": "Source With Link",
                    "content": "Source content",
                    "event_date_range": {
                        "start": "2024-07-01T10:00:00Z",
                        "end": "2024-07-01T11:00:00Z",
                    },
                },
            }
        },
    )
    assert source_res.status_code == 201
    source_id = int(source_res.json()["data"]["id"])

    # 3. Only the source has an external event link
    await async_connection.execute(
        text("""
            INSERT INTO journal_external_event_links
                (journal_id, calendar_id, external_event_id, sync_capability, sync_status)
            VALUES (:jid, :cid, :eid, 'bidirectional', 'synced')
        """),
        {
            "jid": source_id,
            "cid": calendar_id,
            "eid": "source-only-event-999",
        },
    )

    # 4. Merge — must not violate unique index on (calendar_id, external_event_id)
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

    # 5. Verify link was moved to target
    result = await async_connection.execute(
        text("""
            SELECT external_event_id
            FROM journal_external_event_links
            WHERE journal_id = :jid AND calendar_id = :cid
        """),
        {"jid": target_id, "cid": calendar_id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "source-only-event-999"


async def _create_journal(
    client: AsyncClient,
    title: str,
    day: str,
    parent_id: int | None = None,
    *,
    types: list[str] | None = None,
    type_data: dict[str, Any] | None = None,
) -> int:
    """Create a journal via the API and return its id."""
    attributes: dict[str, Any] = {
        "title": title,
        "content": f"{title} content",
        "event_date_range": {
            "start": f"2024-01-{day}T00:00:00Z",
            "end": f"2024-01-{day}T01:00:00Z",
        },
    }
    if parent_id is not None:
        attributes["parent_id"] = parent_id
    if types is not None:
        attributes["types"] = types
    if type_data is not None:
        attributes["type_data"] = type_data

    res = await client.post(
        "/api/journals",
        json={"data": {"type": "journals", "attributes": attributes}},
    )
    assert res.status_code == 201, res.text
    return int(res.json()["data"]["id"])


async def _create_contact(connection: AsyncConnection, first_name: str) -> int:
    """Create a contact directly and return its id."""
    return await seed_contact(connection, first_name=first_name)


async def _add_participant(
    connection: AsyncConnection,
    journal_id: int,
    contact_id: int,
    status: str | None,
    role: str | None,
) -> None:
    """Attach a contact to a journal as a PARTICIPANT with optional status/role."""
    from sqlalchemy import text

    await connection.execute(
        text("""
            INSERT INTO journal_contact_relationships
                (journal_id, contact_id, relationship_type, status, role)
            VALUES (:journal_id, :contact_id, 'PARTICIPANT', :status, :role)
        """),
        {
            "journal_id": journal_id,
            "contact_id": contact_id,
            "status": status,
            "role": role,
        },
    )


async def _get_participant(
    connection: AsyncConnection, journal_id: int, contact_id: int
) -> tuple[str | None, str | None]:
    """Return (status, role) for a journal's participant row."""
    from sqlalchemy import text

    result = await connection.execute(
        text("""
            SELECT status, role
            FROM journal_contact_relationships
            WHERE journal_id = :journal_id
              AND contact_id = :contact_id
              AND relationship_type = 'PARTICIPANT'
        """),
        {"journal_id": journal_id, "contact_id": contact_id},
    )
    row = result.fetchone()
    assert row is not None, "expected a participant row on the target journal"
    return row[0], row[1]


async def _merge(client: AsyncClient, target_id: int, source_id: int) -> None:
    """Merge source into target via the API."""
    res = await client.post(
        f"/api/journals/{target_id}/merge",
        json={
            "data": {
                "type": "journal-merge",
                "attributes": {"source_journal_id": source_id},
            }
        },
    )
    assert res.status_code == 200, res.text


@pytest.mark.integration
async def test_merge_preserves_participant_role_and_status(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """A participant only on the source keeps its status and role after merging."""
    target_id = await _create_journal(authenticated_client, "Target", "01")
    source_id = await _create_journal(authenticated_client, "Source", "02")
    contact_id = await _create_contact(async_connection, "Attendee")

    await _add_participant(
        async_connection, source_id, contact_id, status="ATTENDING", role="ORGANISER"
    )

    await _merge(authenticated_client, target_id, source_id)

    status, role = await _get_participant(async_connection, target_id, contact_id)
    assert status == "ATTENDING"
    assert role == "ORGANISER"


@pytest.mark.integration
async def test_merge_backfills_null_participant_fields(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """An existing target participant with empty fields is backfilled from the source."""
    target_id = await _create_journal(authenticated_client, "Target", "01")
    source_id = await _create_journal(authenticated_client, "Source", "02")
    contact_id = await _create_contact(async_connection, "Attendee")

    await _add_participant(
        async_connection, target_id, contact_id, status=None, role=None
    )
    await _add_participant(
        async_connection, source_id, contact_id, status="MAYBE", role="ORGANISER"
    )

    await _merge(authenticated_client, target_id, source_id)

    status, role = await _get_participant(async_connection, target_id, contact_id)
    assert status == "MAYBE"
    assert role == "ORGANISER"


@pytest.mark.integration
async def test_merge_does_not_overwrite_existing_participant_fields(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """The target's own status and role win over conflicting source values."""
    target_id = await _create_journal(authenticated_client, "Target", "01")
    source_id = await _create_journal(authenticated_client, "Source", "02")
    contact_id = await _create_contact(async_connection, "Attendee")

    await _add_participant(
        async_connection,
        target_id,
        contact_id,
        status="ATTENDING",
        role="FACILITATOR_HELPER",
    )
    await _add_participant(
        async_connection, source_id, contact_id, status="DECLINED", role="ORGANISER"
    )

    await _merge(authenticated_client, target_id, source_id)

    status, role = await _get_participant(async_connection, target_id, contact_id)
    assert status == "ATTENDING"
    assert role == "FACILITATOR_HELPER"


@pytest.mark.integration
async def test_merge_preserves_null_when_neither_participant_set(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """Merging never invents a status or role that was not set on either side."""
    target_id = await _create_journal(authenticated_client, "Target", "01")
    source_id = await _create_journal(authenticated_client, "Source", "02")
    contact_id = await _create_contact(async_connection, "Attendee")

    await _add_participant(
        async_connection, target_id, contact_id, status=None, role=None
    )
    await _add_participant(
        async_connection, source_id, contact_id, status=None, role=None
    )

    await _merge(authenticated_client, target_id, source_id)

    status, role = await _get_participant(async_connection, target_id, contact_id)
    assert status is None
    assert role is None


async def _create_fitness_journal(
    client: AsyncClient, title: str, day: str, fitness: dict[str, Any]
) -> int:
    """Create a FITNESS journal via the API and return its id."""
    res = await client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": title,
                    "content": f"{title} content",
                    "event_date_range": {
                        "start": f"2024-01-{day}T00:00:00Z",
                        "end": f"2024-01-{day}T01:00:00Z",
                    },
                    "types": ["FITNESS"],
                    "type_data": {"FITNESS": fitness},
                },
            }
        },
    )
    assert res.status_code == 201, res.text
    return int(res.json()["data"]["id"])


async def _fitness_after_merge(
    client: AsyncClient, target_id: int, source_id: int, **attributes: Any
) -> dict[str, Any]:
    """Merge, then return the target's fitness type data."""
    res = await client.post(
        f"/api/journals/{target_id}/merge",
        json={
            "data": {
                "type": "journal-merge",
                "attributes": {"source_journal_id": source_id, **attributes},
            }
        },
    )
    assert res.status_code == 200, res.text

    detail = await client.get(f"/api/journals/{target_id}")
    assert detail.status_code == 200, detail.text
    fitness: dict[str, Any] = detail.json()["data"]["attributes"]["type_data"][
        "fitness"
    ]
    return fitness


@pytest.mark.integration
async def test_merge_endpoint_additive_mode_sums_fitness_metrics(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """Two halves of one ride add up when the caller asks for an additive merge."""
    target_id = await _create_fitness_journal(
        authenticated_client,
        "Ride part 1",
        "01",
        {"distance": 5000, "duration": 1800, "elevation_gain": 50, "calories": 300},
    )
    source_id = await _create_fitness_journal(
        authenticated_client,
        "Ride part 2",
        "02",
        {"distance": 3000, "duration": 1200, "elevation_gain": 30, "calories": 200},
    )

    fitness = await _fitness_after_merge(
        authenticated_client, target_id, source_id, fitness_merge_mode="additive"
    )

    assert fitness["distance"] == 8000
    assert fitness["duration"] == 3000
    assert fitness["elevation_gain"] == 80
    assert fitness["calories"] == 500


@pytest.mark.integration
async def test_merge_endpoint_defaults_to_replacing_fitness_metrics(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """Omitting the mode keeps the pre-existing behaviour: the target's numbers stand."""
    target_id = await _create_fitness_journal(
        authenticated_client, "Ride", "01", {"distance": 5000, "duration": 1800}
    )
    source_id = await _create_fitness_journal(
        authenticated_client,
        "Ride re-import",
        "02",
        {"distance": 3000, "duration": 1200, "calories": 200},
    )

    fitness = await _fitness_after_merge(authenticated_client, target_id, source_id)

    assert fitness["distance"] == 5000
    assert fitness["duration"] == 1800
    assert fitness["calories"] == 200  # gaps still fill from the source


@pytest.mark.integration
async def test_merge_endpoint_rejects_an_unknown_fitness_merge_mode(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """An unrecognised mode is a request error, not a silent fallback."""
    target_id = await _create_journal(authenticated_client, "Target", "01")
    source_id = await _create_journal(authenticated_client, "Source", "02")

    res = await authenticated_client.post(
        f"/api/journals/{target_id}/merge",
        json={
            "data": {
                "type": "journal-merge",
                "attributes": {
                    "source_journal_id": source_id,
                    "fitness_merge_mode": "sum-everything",
                },
            }
        },
    )

    assert res.status_code == 400, res.text
    assert res.json()["errors"][0]["source"]["pointer"].endswith("fitness_merge_mode")


async def _create_event_calendar(connection: AsyncConnection, name: str) -> str:
    """Create a calendar directly and return its id."""
    from uuid import uuid4

    calendar_id = uuid4()
    await connection.execute(
        text("""
            INSERT INTO calendars (id, user_id, name, color)
            VALUES (:id, :user_id, :name, :color)
        """),
        {
            "id": calendar_id,
            "user_id": "test-user-123",
            "name": name,
            "color": "#3B82F6",
        },
    )
    return str(calendar_id)


async def _create_event_journal(
    client: AsyncClient,
    title: str,
    day: str,
    calendar_id: str,
    start_time: str,
    end_time: str,
) -> int:
    """Create an EVENT journal with clock times via the API and return its id."""
    res = await client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": title,
                    "content": f"{title} content",
                    "event_date_range": {
                        "start": f"2024-01-{day}T08:00:00Z",
                        "end": f"2024-01-{day}T12:00:00Z",
                    },
                    "types": ["EVENT"],
                    "type_data": {
                        "EVENT": {
                            "calendar_id": calendar_id,
                            "start_time": start_time,
                            "end_time": end_time,
                            "is_all_day": False,
                        }
                    },
                },
            }
        },
    )
    assert res.status_code == 201, res.text
    return int(res.json()["data"]["id"])


@pytest.mark.integration
async def test_merge_endpoint_accepts_clock_time_type_data_overrides(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """A time override arrives as a JSON string and must reach a TIME column typed.

    The merge panel echoes back what the read API gave it, so ``start_time`` is
    ``'19:30:00'`` rather than a ``time``. Binding that straight into the UPDATE
    made asyncpg fail with "'str' object has no attribute 'hour'".
    """
    from datetime import time

    calendar_id = await _create_event_calendar(async_connection, "Shared Calendar")
    target_id = await _create_event_journal(
        authenticated_client, "Target event", "01", calendar_id, "09:00:00", "10:00:00"
    )
    source_id = await _create_event_journal(
        authenticated_client, "Source event", "01", calendar_id, "19:30:00", "22:00:00"
    )

    res = await authenticated_client.post(
        f"/api/journals/{target_id}/merge",
        json={
            "data": {
                "type": "journal-merge",
                "attributes": {
                    "source_journal_id": source_id,
                    "overrides": {
                        "type_data": {
                            "event": {
                                "start_time": "19:30:00",
                                "end_time": "22:00:00",
                            }
                        }
                    },
                },
            }
        },
    )

    assert res.status_code == 200, res.text

    row = (
        await async_connection.execute(
            text(
                "SELECT start_time, end_time FROM journal_calendar_info"
                " WHERE journal_id = :id"
            ),
            {"id": target_id},
        )
    ).fetchone()
    assert row is not None
    assert row.start_time == time(19, 30)
    assert row.end_time == time(22, 0)


@pytest.mark.integration
async def test_merge_endpoint_rejects_an_unparseable_time_override(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """Garbage in a typed column is the caller's error, not a driver crash."""
    calendar_id = await _create_event_calendar(async_connection, "Shared Calendar")
    target_id = await _create_event_journal(
        authenticated_client, "Target event", "01", calendar_id, "09:00:00", "10:00:00"
    )
    source_id = await _create_event_journal(
        authenticated_client, "Source event", "01", calendar_id, "19:30:00", "22:00:00"
    )

    res = await authenticated_client.post(
        f"/api/journals/{target_id}/merge",
        json={
            "data": {
                "type": "journal-merge",
                "attributes": {
                    "source_journal_id": source_id,
                    "overrides": {
                        "type_data": {"event": {"start_time": "half past seven"}}
                    },
                },
            }
        },
    )

    assert res.status_code == 400, res.text


@pytest.mark.integration
async def test_merge_endpoint_rejects_a_wrong_typed_time_override(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """A number is no more bindable to a TIME column than a bad string is.

    The request schema types type-data values as ``Any``, so a payload like
    ``{"start_time": 1930}`` reaches the UPDATE with the wrong Python type.
    """
    calendar_id = await _create_event_calendar(async_connection, "Shared Calendar")
    target_id = await _create_event_journal(
        authenticated_client, "Target event", "01", calendar_id, "09:00:00", "10:00:00"
    )
    source_id = await _create_event_journal(
        authenticated_client, "Source event", "01", calendar_id, "19:30:00", "22:00:00"
    )

    res = await authenticated_client.post(
        f"/api/journals/{target_id}/merge",
        json={
            "data": {
                "type": "journal-merge",
                "attributes": {
                    "source_journal_id": source_id,
                    "overrides": {"type_data": {"event": {"start_time": 1930}}},
                },
            }
        },
    )

    assert res.status_code == 400, res.text


@pytest.mark.integration
async def test_merge_endpoint_turns_an_allday_target_timed_when_asked(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """Keeping a timed source's range must not leave the event marked all-day.

    The merge panel folds ``is_all_day`` in with the range, so the two arrive
    together; the merged row then takes the source's clock times rather than
    having them cleared as an all-day event's times are.
    """
    from datetime import time

    calendar_id = await _create_event_calendar(async_connection, "Shared Calendar")

    all_day_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "All day target",
                    "content": "All day content",
                    "event_date_range": {
                        "start": "2024-01-01T00:00:00Z",
                        "end": "2024-01-01T23:59:59Z",
                    },
                    "types": ["EVENT"],
                    "type_data": {
                        "EVENT": {"calendar_id": calendar_id, "is_all_day": True}
                    },
                },
            }
        },
    )
    assert all_day_res.status_code == 201, all_day_res.text
    target_id = int(all_day_res.json()["data"]["id"])

    source_id = await _create_event_journal(
        authenticated_client, "Timed source", "01", calendar_id, "19:30:00", "22:00:00"
    )

    res = await authenticated_client.post(
        f"/api/journals/{target_id}/merge",
        json={
            "data": {
                "type": "journal-merge",
                "attributes": {
                    "source_journal_id": source_id,
                    "overrides": {
                        "event_date_range": {
                            "start": "2024-01-01T08:00:00Z",
                            "end": "2024-01-01T12:00:00Z",
                        },
                        "type_data": {"event": {"is_all_day": False}},
                    },
                },
            }
        },
    )

    assert res.status_code == 200, res.text

    row = (
        await async_connection.execute(
            text(
                "SELECT is_all_day, start_time, end_time FROM journal_calendar_info"
                " WHERE journal_id = :id"
            ),
            {"id": target_id},
        )
    ).fetchone()
    assert row is not None
    assert row.is_all_day is False
    assert row.start_time == time(19, 30)
    assert row.end_time == time(22, 0)


@pytest.mark.integration
async def test_merge_endpoint_honours_an_explicit_null_timezone_override(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """ "No zone" is an answer, and must beat the fill-from-source default.

    A synced event carries a timezone where a hand-written one does not. Keeping
    the zoneless side's clock times has to keep them zoneless too, or the other
    side's zone survives and re-reads them.
    """
    calendar_id = await _create_event_calendar(async_connection, "Shared Calendar")
    target_id = await _create_event_journal(
        authenticated_client, "Target event", "01", calendar_id, "09:00:00", "10:00:00"
    )
    source_id = await _create_event_journal(
        authenticated_client, "Source event", "01", calendar_id, "19:30:00", "22:00:00"
    )
    await async_connection.execute(
        text("UPDATE journal_calendar_info SET timezone = :tz WHERE journal_id = :id"),
        {"tz": "Pacific/Auckland", "id": source_id},
    )

    res = await authenticated_client.post(
        f"/api/journals/{target_id}/merge",
        json={
            "data": {
                "type": "journal-merge",
                "attributes": {
                    "source_journal_id": source_id,
                    "overrides": {
                        "type_data": {
                            "event": {
                                "start_time": "09:00:00",
                                "end_time": "10:00:00",
                                "timezone": None,
                            }
                        }
                    },
                },
            }
        },
    )

    assert res.status_code == 200, res.text

    row = (
        await async_connection.execute(
            text("SELECT timezone FROM journal_calendar_info WHERE journal_id = :id"),
            {"id": target_id},
        )
    ).fetchone()
    assert row is not None
    assert row.timezone is None


@pytest.mark.asyncio
async def test_merge_carries_the_sources_series_memberships_to_the_target(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
) -> None:
    """A merged-away journal's series keep the journal that absorbed it.

    Series memberships cascade when a journal is deleted, so without moving
    them a merge silently dropped the survivor out of every series only the
    source belonged to. A series both already share keeps one membership.
    """
    only_source = await seed_series(async_connection, "Physio")
    shared = await seed_series(async_connection, "Health")
    target_id = await seed_member(
        async_connection,
        shared,
        title="Survivor",
        start=datetime(2026, 8, 3, tzinfo=UTC),
    )
    source_id = await seed_member(
        async_connection,
        only_source,
        title="Absorbed",
        start=datetime(2026, 8, 3, tzinfo=UTC),
    )
    await add_to_series(async_connection, shared, source_id)

    await _merge(authenticated_client, target_id, source_id)

    assert await member_ids(async_connection, only_source) == {target_id}
    assert await member_ids(async_connection, shared) == {target_id}
