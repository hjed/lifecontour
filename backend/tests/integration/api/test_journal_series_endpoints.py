"""Integration tests for journal series API endpoints."""

from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio


def _series_request(
    name: str = "Physio appointments", description: str | None = None
) -> dict[str, Any]:
    attributes: dict[str, Any] = {"name": name}
    if description is not None:
        attributes["description"] = description
    return {"data": {"type": "journal-series", "attributes": attributes}}


def _journal_request(title: str = "Series member journal") -> dict[str, Any]:
    return {
        "data": {
            "type": "journals",
            "attributes": {
                "title": title,
                "content": "",
                "event_date_range": {
                    "start": datetime.now(UTC).isoformat(),
                    "end": datetime.now(UTC).isoformat(),
                },
            },
        }
    }


async def _create_series(client, name: str = "Physio appointments") -> str:
    response = await client.post("/api/journals/series", json=_series_request(name))
    assert response.status_code == 201
    return str(response.json()["data"]["id"])


async def _create_journal(client, title: str = "Series member journal") -> int:
    response = await client.post("/api/journals", json=_journal_request(title))
    assert response.status_code == 201
    return int(response.json()["data"]["id"])


@pytest.mark.integration
class TestJournalSeriesCRUD:
    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        pass

    async def test_create_series_returns_201_json_api_resource(
        self, integration_api_client
    ) -> None:
        response = await integration_api_client.post(
            "/api/journals/series",
            json=_series_request(description="Weekly knee physio"),
        )

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["type"] == "journal-series"
        assert data["id"]
        assert data["attributes"]["name"] == "Physio appointments"
        assert data["attributes"]["description"] == "Weekly knee physio"
        assert data["attributes"]["auto_created"] is False

    async def test_create_series_empty_name_rejected(
        self, integration_api_client
    ) -> None:
        response = await integration_api_client.post(
            "/api/journals/series", json=_series_request(name="   ")
        )

        assert response.status_code in (400, 422)

    async def test_list_series_ordered_by_name(self, integration_api_client) -> None:
        await _create_series(integration_api_client, name="Zebra series")
        await _create_series(integration_api_client, name="Alpha series")

        response = await integration_api_client.get("/api/journals/series")

        assert response.status_code == 200
        names = [item["attributes"]["name"] for item in response.json()["data"]]
        assert names == ["Alpha series", "Zebra series"]

    async def test_get_series_includes_member_journals(
        self, integration_api_client
    ) -> None:
        series_id = await _create_series(integration_api_client)
        journal_id = await _create_journal(integration_api_client)
        add = await integration_api_client.post(
            f"/api/journals/{journal_id}/relationships/series",
            json={"data": {"type": "journal-series", "id": series_id}},
        )
        assert add.status_code == 204

        response = await integration_api_client.get(f"/api/journals/series/{series_id}")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["id"] == series_id
        members = data["attributes"]["member_journals"]
        assert len(members) == 1
        assert members[0]["id"] == journal_id
        assert members[0]["title"] == "Series member journal"

    async def test_patch_series_renames(self, integration_api_client) -> None:
        series_id = await _create_series(integration_api_client)

        response = await integration_api_client.patch(
            f"/api/journals/series/{series_id}",
            json={
                "data": {
                    "type": "journal-series",
                    "id": series_id,
                    "attributes": {
                        "name": "Renamed series",
                        "description": "now with description",
                    },
                }
            },
        )

        assert response.status_code == 200
        attributes = response.json()["data"]["attributes"]
        assert attributes["name"] == "Renamed series"
        assert attributes["description"] == "now with description"

    async def test_delete_series_leaves_member_journals(
        self, integration_api_client
    ) -> None:
        series_id = await _create_series(integration_api_client)
        journal_id = await _create_journal(integration_api_client)
        await integration_api_client.post(
            f"/api/journals/{journal_id}/relationships/series",
            json={"data": {"type": "journal-series", "id": series_id}},
        )

        response = await integration_api_client.delete(
            f"/api/journals/series/{series_id}"
        )
        assert response.status_code == 204

        assert (
            await integration_api_client.get(f"/api/journals/series/{series_id}")
        ).status_code == 404
        journal_response = await integration_api_client.get(
            f"/api/journals/{journal_id}"
        )
        assert journal_response.status_code == 200

    async def test_get_unknown_series_returns_404(self, integration_api_client) -> None:
        response = await integration_api_client.get(
            "/api/journals/series/00000000-0000-0000-0000-000000000042"
        )

        assert response.status_code == 404


@pytest.mark.integration
class TestJournalSeriesMembership:
    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        pass

    async def test_add_and_remove_journal_membership(
        self, integration_api_client
    ) -> None:
        series_id = await _create_series(integration_api_client)
        journal_id = await _create_journal(integration_api_client)

        add = await integration_api_client.post(
            f"/api/journals/{journal_id}/relationships/series",
            json={"data": {"type": "journal-series", "id": series_id}},
        )
        assert add.status_code == 204

        detail = await integration_api_client.get(f"/api/journals/{journal_id}")
        series_list = detail.json()["data"]["attributes"]["series"]
        assert series_list == [{"id": series_id, "name": "Physio appointments"}]

        remove = await integration_api_client.delete(
            f"/api/journals/{journal_id}/relationships/series/{series_id}"
        )
        assert remove.status_code == 204

        detail = await integration_api_client.get(f"/api/journals/{journal_id}")
        assert detail.json()["data"]["attributes"]["series"] == []

    async def test_add_unknown_journal_returns_404(
        self, integration_api_client
    ) -> None:
        series_id = await _create_series(integration_api_client)

        response = await integration_api_client.post(
            "/api/journals/999999/relationships/series",
            json={"data": {"type": "journal-series", "id": series_id}},
        )

        assert response.status_code == 404

    async def test_add_unknown_series_returns_404(self, integration_api_client) -> None:
        journal_id = await _create_journal(integration_api_client)

        response = await integration_api_client.post(
            f"/api/journals/{journal_id}/relationships/series",
            json={
                "data": {
                    "type": "journal-series",
                    "id": "00000000-0000-0000-0000-000000000042",
                }
            },
        )

        assert response.status_code == 404

    async def test_patch_series_with_mismatched_body_id_returns_400(
        self, integration_api_client
    ) -> None:
        series_id = await _create_series(integration_api_client)

        response = await integration_api_client.patch(
            f"/api/journals/series/{series_id}",
            json={
                "data": {
                    "type": "journal-series",
                    "id": "00000000-0000-0000-0000-000000000042",
                    "attributes": {"name": "Renamed"},
                }
            },
        )

        assert response.status_code == 400
        # The series is unchanged.
        detail = await integration_api_client.get(f"/api/journals/series/{series_id}")
        assert detail.json()["data"]["attributes"]["name"] == "Physio appointments"
