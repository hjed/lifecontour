"""Integration tests for the incomplete outdoor activities REST endpoints.

Exercises the list / dismiss / undismiss endpoints end-to-end via the
``authenticated_client``. Each test seeds its own journals through the real
repositories (savepoint-isolated), so outcomes are deterministic.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from core_shared.models.history import Provenance
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.journal.outdoor_activity_seeding import (
    OTHER_USER_ID,
    USER_ID,
    Seeder,
)

pytestmark = pytest.mark.asyncio

LIST_URL = "/api/journals/incomplete-outdoor-activities"


@pytest_asyncio.fixture
async def seeder(async_connection: AsyncConnection) -> Seeder:
    return Seeder(async_connection)


async def fetch_dismissal_provenance(
    async_connection: AsyncConnection, journal_id: int
) -> str | None:
    result = await async_connection.execute(
        text(
            "SELECT provenance FROM outdoor_activity_dismissals"
            " WHERE journal_id = :journal_id AND user_id = :user_id"
        ),
        {"journal_id": journal_id, "user_id": USER_ID},
    )
    return result.scalar()


async def test_list_empty_when_no_incomplete_activities(authenticated_client) -> None:
    response = await authenticated_client.get(LIST_URL)

    assert response.status_code == 200
    assert response.json()["data"] == []


async def test_list_returns_entry_with_reasons_subtypes_and_date_range(
    authenticated_client,
    seeder: Seeder,
) -> None:
    journal_id = await seeder.create_incomplete_canyoning_journal()

    response = await authenticated_client.get(LIST_URL)

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    resource = data[0]
    assert resource["type"] == "incomplete-outdoor-activities"
    assert resource["id"] == str(journal_id)
    attributes = resource["attributes"]
    assert attributes["title"] == "Empty canyon"
    assert attributes["reasons"] == [
        "no_attributes",
        "missing_template",
        "no_participants",
    ]
    assert "canyoning" in attributes["subtypes"]
    assert attributes["event_date_range"]["start"] is not None
    assert attributes["event_date_range"]["end"] is not None
    assert resource["links"]["self"].endswith(f"/api/journals/{journal_id}")


async def test_list_orders_newest_first(
    authenticated_client,
    seeder: Seeder,
) -> None:
    older_id = await seeder.create_incomplete_canyoning_journal(
        title="Older canyon", start=datetime(2026, 3, 1, 9, tzinfo=UTC)
    )
    newer_id = await seeder.create_incomplete_canyoning_journal(
        title="Newer canyon", start=datetime(2026, 6, 1, 9, tzinfo=UTC)
    )

    response = await authenticated_client.get(LIST_URL)

    assert response.status_code == 200
    listed_ids = [entry["id"] for entry in response.json()["data"]]
    assert listed_ids == [str(newer_id), str(older_id)]


async def test_list_marks_entries_not_dismissed_by_default(
    authenticated_client,
    seeder: Seeder,
) -> None:
    await seeder.create_incomplete_canyoning_journal()

    response = await authenticated_client.get(LIST_URL)

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["attributes"]["dismissed"] is False


async def test_list_include_dismissed_returns_dismissed_entries_flagged(
    authenticated_client,
    seeder: Seeder,
) -> None:
    dismissed_id = await seeder.create_incomplete_canyoning_journal(
        title="Dismissed canyon", start=datetime(2026, 6, 1, 9, tzinfo=UTC)
    )
    live_id = await seeder.create_incomplete_canyoning_journal(
        title="Live canyon", start=datetime(2026, 3, 1, 9, tzinfo=UTC)
    )
    dismiss_response = await authenticated_client.post(
        f"{LIST_URL}/{dismissed_id}/dismiss"
    )
    assert dismiss_response.status_code == 200

    # Default list still excludes the dismissed journal.
    default_response = await authenticated_client.get(LIST_URL)
    assert default_response.status_code == 200
    assert [entry["id"] for entry in default_response.json()["data"]] == [str(live_id)]

    response = await authenticated_client.get(
        LIST_URL, params={"include_dismissed": "true"}
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert [entry["id"] for entry in data] == [str(dismissed_id), str(live_id)]
    assert data[0]["attributes"]["dismissed"] is True
    assert data[1]["attributes"]["dismissed"] is False


async def test_dismiss_removes_entry_and_records_ui_provenance(
    authenticated_client,
    seeder: Seeder,
    async_connection: AsyncConnection,
) -> None:
    journal_id = await seeder.create_incomplete_canyoning_journal()

    response = await authenticated_client.post(f"{LIST_URL}/{journal_id}/dismiss")

    assert response.status_code == 200
    attributes = response.json()["data"]["attributes"]
    assert attributes["journal_id"] == journal_id
    assert attributes["dismissed"] is True
    assert attributes["provenance"] == "ui"

    assert (
        await fetch_dismissal_provenance(async_connection, journal_id)
        == Provenance.UI.value
    )

    list_response = await authenticated_client.get(LIST_URL)
    assert list_response.json()["data"] == []


async def test_dismiss_unknown_journal_returns_404(authenticated_client) -> None:
    response = await authenticated_client.post(f"{LIST_URL}/999999/dismiss")

    assert response.status_code == 404


async def test_dismiss_other_users_journal_returns_404(
    authenticated_client,
    seeder: Seeder,
    async_connection: AsyncConnection,
) -> None:
    journal_id = await seeder.create_incomplete_canyoning_journal(
        title="Someone else's canyon", user_id=OTHER_USER_ID
    )

    response = await authenticated_client.post(f"{LIST_URL}/{journal_id}/dismiss")

    assert response.status_code == 404
    assert await fetch_dismissal_provenance(async_connection, journal_id) is None


async def test_undismiss_restores_entry(
    authenticated_client,
    seeder: Seeder,
) -> None:
    journal_id = await seeder.create_incomplete_canyoning_journal()
    dismiss_response = await authenticated_client.post(
        f"{LIST_URL}/{journal_id}/dismiss"
    )
    assert dismiss_response.status_code == 200

    response = await authenticated_client.post(f"{LIST_URL}/{journal_id}/undismiss")

    assert response.status_code == 200
    attributes = response.json()["data"]["attributes"]
    assert attributes["journal_id"] == journal_id
    assert attributes["dismissed"] is False
    assert attributes["was_dismissed"] is True

    list_response = await authenticated_client.get(LIST_URL)
    listed_ids = [entry["id"] for entry in list_response.json()["data"]]
    assert listed_ids == [str(journal_id)]


async def test_undismiss_never_dismissed_returns_200_noop(
    authenticated_client,
    seeder: Seeder,
) -> None:
    journal_id = await seeder.create_incomplete_canyoning_journal()

    response = await authenticated_client.post(f"{LIST_URL}/{journal_id}/undismiss")

    assert response.status_code == 200
    attributes = response.json()["data"]["attributes"]
    assert attributes["dismissed"] is False
    assert attributes["was_dismissed"] is False


async def test_undismiss_unknown_journal_returns_404(authenticated_client) -> None:
    response = await authenticated_client.post(f"{LIST_URL}/999999/undismiss")

    assert response.status_code == 404


async def test_undismiss_other_users_journal_returns_404(
    authenticated_client,
    seeder: Seeder,
) -> None:
    journal_id = await seeder.create_incomplete_canyoning_journal(
        title="Someone else's canyon", user_id=OTHER_USER_ID
    )

    response = await authenticated_client.post(f"{LIST_URL}/{journal_id}/undismiss")

    assert response.status_code == 404
