"""Integration tests for the journal merge endpoint."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


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
    client: AsyncClient, title: str, day: str, parent_id: int | None = None
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

    res = await client.post(
        "/api/journals",
        json={"data": {"type": "journals", "attributes": attributes}},
    )
    assert res.status_code == 201, res.text
    return int(res.json()["data"]["id"])


async def _create_contact(connection: AsyncConnection, first_name: str) -> int:
    """Create a contact directly and return its id."""
    from sqlalchemy import text

    result = await connection.execute(
        text("INSERT INTO contacts (first_name) VALUES (:first_name) RETURNING id"),
        {"first_name": first_name},
    )
    contact_id = result.scalar()
    assert contact_id is not None
    return int(contact_id)


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
