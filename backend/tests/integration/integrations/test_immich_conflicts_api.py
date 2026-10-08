import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.contact_seeding import TEST_USER_ID, seed_contact


@pytest.fixture
async def pending_conflict(
    async_connection: AsyncConnection,
    test_user,
) -> int:
    """Create a pending entity mapping conflict for testing."""
    query = text("""
        INSERT INTO pending_entity_mappings
            (user_id, integration_source, external_entity_id,
             external_entity_name, candidate_contact_ids, status,
             created_at, updated_at)
        VALUES
            (:user_id, 'immich', 'person-123',
             'John Doe', '[1, 2]'::jsonb,
             'unresolved', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id
    """)
    result = await async_connection.execute(query, {"user_id": str(test_user.id)})
    inserted_id = result.scalar_one()
    assert isinstance(inserted_id, int)
    return inserted_id


@pytest.mark.asyncio
async def test_list_immich_conflicts(
    authenticated_client: AsyncClient,
    pending_conflict: int,
) -> None:
    """Verify that unresolved conflicts can be listed."""
    response = await authenticated_client.get("/api/integrations/immich/conflicts")
    assert response.status_code == 200

    data = response.json()
    assert "data" in data

    conflicts = data["data"]
    assert len(conflicts) == 1

    conflict = next(c for c in conflicts if c["id"] == str(pending_conflict))
    assert conflict["type"] == "immich-conflict"
    assert conflict["attributes"]["externalEntityId"] == "person-123"
    assert conflict["attributes"]["externalEntityName"] == "John Doe"
    assert conflict["attributes"]["candidateContactIds"] == [1, 2]
    assert conflict["attributes"]["status"] == "unresolved"


@pytest.mark.asyncio
async def test_list_immich_conflicts_includes_candidate_names(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    test_user,
) -> None:
    """Candidate contacts are returned with resolved display names and photos."""
    # Create two real contacts to act as candidates
    contact_ids = [
        await seed_contact(
            async_connection,
            first_name="Nikhil",
            last_name="Sharma",
            photo_url="https://photos/nikhil.jpg",
        ),
        await seed_contact(async_connection, first_name="Nicole"),
    ]
    missing_id = 999999  # No contact row -> falls back to "Contact {id}"

    # Conflict referencing both real contacts plus a missing id, order preserved
    candidate_json = f"[{contact_ids[0]}, {missing_id}, {contact_ids[1]}]"
    insert_conflict = text("""
        INSERT INTO pending_entity_mappings
            (user_id, integration_source, external_entity_id,
             external_entity_name, candidate_contact_ids, status,
             created_at, updated_at)
        VALUES
            (:user_id, 'immich', 'person-names',
             'Nikhil Sharma', CAST(:candidates AS jsonb),
             'unresolved', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id
    """)
    res = await async_connection.execute(
        insert_conflict,
        {"user_id": str(test_user.id), "candidates": candidate_json},
    )
    conflict_id = res.scalar_one()

    response = await authenticated_client.get("/api/integrations/immich/conflicts")
    assert response.status_code == 200

    conflicts = response.json()["data"]
    conflict = next(c for c in conflicts if c["id"] == str(conflict_id))
    candidates = conflict["attributes"]["candidateContacts"]

    # Order is preserved and matches candidateContactIds
    assert [c["id"] for c in candidates] == [contact_ids[0], missing_id, contact_ids[1]]
    assert candidates[0]["name"] == "Nikhil Sharma"
    assert candidates[0]["photoUrl"] == "https://photos/nikhil.jpg"
    # Missing contact falls back to "Contact {id}" with no photo
    assert candidates[1]["name"] == f"Contact {missing_id}"
    assert candidates[1]["photoUrl"] is None
    # Contact with only a first name uses just that name
    assert candidates[2]["name"] == "Nicole"
    assert candidates[2]["photoUrl"] is None


@pytest.mark.asyncio
async def test_resolve_immich_conflict_link(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    pending_conflict: int,
    test_user,
) -> None:
    """Verify that a conflict can be resolved by linking an existing contact."""
    # First, create a contact
    contact_id = await seed_contact(
        async_connection, first_name="John", last_name="Doe"
    )

    # Resolve the conflict
    response = await authenticated_client.post(
        f"/api/integrations/immich/conflicts/{pending_conflict}/resolve",
        json={"action": "link", "contact_id": contact_id},
    )
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["attributes"]["status"] == "resolved"

    # Check that it's resolved in the DB
    check_query = text("""
        SELECT status, resolved_contact_id
        FROM pending_entity_mappings
        WHERE id = :id
    """)
    res = await async_connection.execute(check_query, {"id": pending_conflict})
    row = res.fetchone()
    assert row is not None
    assert row.status == "resolved"
    assert row.resolved_contact_id == contact_id

    # Check that the canonical sync_metadata link was created.
    ref_query = text("""
        SELECT external_id
        FROM sync_metadata
        WHERE internal_entity_type = 'contact'
          AND internal_id = :contact_id
          AND integration_source = 'immich'
    """)
    ref_res = await async_connection.execute(ref_query, {"contact_id": contact_id})
    ref_row = ref_res.fetchone()
    assert ref_row is not None
    assert ref_row.external_id == "person-123"


@pytest.mark.asyncio
async def test_resolve_immich_conflict_create(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    pending_conflict: int,
) -> None:
    """Verify that a conflict can be resolved by creating a new contact."""
    # Resolve the conflict by creating a new contact
    response = await authenticated_client.post(
        f"/api/integrations/immich/conflicts/{pending_conflict}/resolve",
        json={"action": "create"},
    )
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["attributes"]["status"] == "resolved"

    # Check that it's resolved in the DB
    check_query = text("""
        SELECT status, resolved_contact_id
        FROM pending_entity_mappings
        WHERE id = :id
    """)
    res = await async_connection.execute(check_query, {"id": pending_conflict})
    row = res.fetchone()
    assert row is not None
    assert row.status == "resolved"
    contact_id = row.resolved_contact_id
    assert contact_id is not None

    # Verify the new contact was created with the person's name, for the user
    # who resolved the conflict
    contact_query = text(
        "SELECT user_id, first_name, last_name FROM contacts WHERE id = :id"
    )
    c_res = await async_connection.execute(contact_query, {"id": contact_id})
    c_row = c_res.fetchone()
    assert c_row is not None
    assert c_row.first_name == "John"
    assert c_row.last_name == "Doe"
    assert c_row.user_id == TEST_USER_ID

    # Check that the canonical sync_metadata link was created.
    ref_query = text("""
        SELECT external_id
        FROM sync_metadata
        WHERE internal_entity_type = 'contact'
          AND internal_id = :contact_id
          AND integration_source = 'immich'
    """)
    ref_res = await async_connection.execute(ref_query, {"contact_id": contact_id})
    ref_row = ref_res.fetchone()
    assert ref_row is not None
    assert ref_row.external_id == "person-123"


@pytest.mark.asyncio
async def test_resolve_immich_conflict_link_nonexistent_contact(
    authenticated_client: AsyncClient,
    pending_conflict: int,
) -> None:
    """Verify that linking to a non-existent contact returns 404."""
    response = await authenticated_client.post(
        f"/api/integrations/immich/conflicts/{pending_conflict}/resolve",
        json={"action": "link", "contact_id": 999999},
    )
    assert response.status_code == 404
    errors = response.json()["errors"]
    assert len(errors) == 1
    assert "not found" in errors[0]["detail"].lower()


@pytest.mark.asyncio
async def test_resolve_immich_conflict_for_a_person_another_user_links(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    pending_conflict: int,
) -> None:
    """Linking a person another user already links is a 409; nothing changes."""
    contact_id = await seed_contact(
        async_connection, first_name="John", last_name="Doe"
    )
    await async_connection.execute(
        text("""
            INSERT INTO sync_metadata
                (user_id, internal_id, integration_source, external_id,
                 last_synced_at, version_hash, sync_status, internal_entity_type)
            VALUES ('other-user-456', 999, 'immich', 'person-123',
                    now(), 'theirs', 'success', 'contact')
        """)
    )

    response = await authenticated_client.post(
        f"/api/integrations/immich/conflicts/{pending_conflict}/resolve",
        json={"action": "link", "contact_id": contact_id},
    )

    assert response.status_code == 409
    assert "other-user-456" not in response.text
    links = (
        await async_connection.execute(
            text(
                "SELECT user_id, internal_id FROM sync_metadata "
                "WHERE external_id = 'person-123'"
            )
        )
    ).fetchall()
    assert [tuple(row) for row in links] == [("other-user-456", 999)]
    status = (
        await async_connection.execute(
            text("SELECT status FROM pending_entity_mappings WHERE id = :id"),
            {"id": pending_conflict},
        )
    ).scalar_one()
    assert status == "unresolved"
