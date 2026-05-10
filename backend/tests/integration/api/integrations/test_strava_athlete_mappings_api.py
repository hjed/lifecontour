import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_athlete_mapping(
    authenticated_client: AsyncClient,
    async_connection,
    contact_factory,
    clean_database,
    test_user,
) -> None:
    """Test creating an athlete mapping."""
    contact = await contact_factory.create_contact("John", "Doe")
    response = await authenticated_client.post(
        "/api/integrations/strava/athlete-mappings",
        json={
            "strava_athlete_id": "athlete_123",
            "strava_athlete_name": "John Doe",
            "contact_id": int(contact["id"]),
        },
    )

    assert response.status_code == 200
    res_data = response.json()
    assert "data" in res_data
    mapping_data = res_data["data"]
    assert mapping_data["type"] == "strava-athlete-mapping"
    assert "id" in mapping_data
    assert mapping_data["attributes"]["strava_athlete_id"] == "athlete_123"
    assert mapping_data["attributes"]["strava_athlete_name"] == "John Doe"
    assert mapping_data["attributes"]["contact_id"] == int(contact["id"])


@pytest.mark.asyncio
async def test_get_athlete_mappings(
    authenticated_client: AsyncClient,
    async_connection,
    contact_factory,
    clean_database,
    test_user,
) -> None:
    """Test retrieving athlete mappings."""
    contact = await contact_factory.create_contact("John", "Doe")
    from sqlalchemy import text

    await async_connection.execute(
        text("""
            INSERT INTO strava_athlete_mappings (user_id, strava_athlete_id, strava_athlete_name, contact_id)
            VALUES (:user_id, 'test_athlete_123', 'John Doe', :contact_id)
        """),
        {"user_id": str(test_user.id), "contact_id": int(contact["id"])},
    )

    response = await authenticated_client.get(
        "/api/integrations/strava/athlete-mappings"
    )

    assert response.status_code == 200
    res_data = response.json()
    assert "data" in res_data
    assert len(res_data["data"]) == 1
    mapping_data = res_data["data"][0]
    assert mapping_data["type"] == "strava-athlete-mapping"
    assert mapping_data["attributes"]["strava_athlete_id"] == "test_athlete_123"


@pytest.mark.asyncio
async def test_delete_athlete_mapping(
    authenticated_client: AsyncClient,
    async_connection,
    contact_factory,
    clean_database,
    test_user,
) -> None:
    """Test deleting an athlete mapping."""
    contact = await contact_factory.create_contact("John", "Doe")
    from sqlalchemy import text

    await async_connection.execute(
        text("""
            INSERT INTO strava_athlete_mappings (user_id, strava_athlete_id, strava_athlete_name, contact_id)
            VALUES (:user_id, 'test_athlete_123', 'John Doe', :contact_id)
        """),
        {"user_id": str(test_user.id), "contact_id": int(contact["id"])},
    )

    response = await authenticated_client.delete(
        "/api/integrations/strava/athlete-mappings/test_athlete_123"
    )
    assert response.status_code == 204

    # Verify it was deleted
    response2 = await authenticated_client.get(
        "/api/integrations/strava/athlete-mappings"
    )
    data = response2.json()
    assert len(data["data"]) == 0


@pytest.mark.asyncio
async def test_get_journal_unmatched_athletes(
    authenticated_client: AsyncClient,
    async_connection,
    test_user,
    sample_journal_id,
    clean_database,
) -> None:
    """Test retrieving unmatched athletes for a journal."""
    journal_id = sample_journal_id

    # Create an unmatched athlete
    from sqlalchemy import text

    await async_connection.execute(
        text("""
            INSERT INTO journal_unmatched_strava_athletes (journal_id, strava_athlete_id, strava_athlete_name)
            VALUES (:journal_id, 'unmatched_1', 'Jane Doe')
        """),
        {"journal_id": journal_id},
    )

    response = await authenticated_client.get(
        f"/api/integrations/strava/journals/{journal_id}/unmatched-athletes"
    )

    assert response.status_code == 200
    res_data = response.json()
    assert "data" in res_data
    assert len(res_data["data"]) == 1
    athlete_data = res_data["data"][0]
    assert athlete_data["type"] == "unmatched-strava-athlete"
    assert athlete_data["id"] == "unmatched_1"
    assert athlete_data["attributes"]["strava_athlete_id"] == "unmatched_1"
    assert athlete_data["attributes"]["strava_athlete_name"] == "Jane Doe"
