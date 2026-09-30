"""Integration tests for merging one journal series into another over REST."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.settings.models import UserSettings
from tests.integration.series_merge_seeding import (
    OTHER_USER_ID,
    USER_ID,
    member_ids,
    seed_calendar,
    seed_member,
    seed_series,
    series_exists,
)


def _merge_body(
    source_series_id: uuid.UUID, policies: dict[str, str] | None = None
) -> dict[str, Any]:
    attributes: dict[str, Any] = {"source_series_id": str(source_series_id)}
    if policies is not None:
        attributes["policies"] = policies
    return {"data": {"type": "journal-series-merge", "attributes": attributes}}


def _preview_url(destination_series_id: uuid.UUID) -> str:
    return f"/api/journals/series/{destination_series_id}/merge/preview"


def _days(response_json: dict[str, Any]) -> list[dict[str, Any]]:
    days: list[dict[str, Any]] = response_json["data"]["attributes"]["days"]
    return days


def _at(day: int, hour: int) -> datetime:
    return datetime(2026, 8, day, hour, tzinfo=UTC)


@pytest.mark.integration
class TestPreviewSeriesMerge:
    async def test_reports_each_day_and_writes_nothing(
        self, integration_api_client: AsyncClient, clean_database: AsyncConnection
    ) -> None:
        calendar = await seed_calendar(clean_database)
        source = await seed_series(clean_database, "Old standup")
        destination = await seed_series(clean_database, "Standup")
        paired_source = await seed_member(
            clean_database, source, title="Old", start=_at(3, 9), calendar_id=calendar
        )
        paired_destination = await seed_member(
            clean_database, destination, title="New", start=_at(3, 9)
        )
        lonely = await seed_member(
            clean_database, source, title="Old", start=_at(10, 9)
        )
        crowded = [
            await seed_member(clean_database, source, title="Old", start=_at(17, h))
            for h in (9, 15)
        ]
        crowded_destination = await seed_member(
            clean_database, destination, title="New", start=_at(17, 9)
        )

        response = await integration_api_client.post(
            _preview_url(destination), json=_merge_body(source)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["type"] == "journal-series-merge-plan"
        assert body["data"]["attributes"]["source_series_id"] == str(source)
        assert [
            (
                d["date"],
                d["kind"],
                d["source_journal_ids"],
                d["destination_journal_ids"],
            )
            for d in _days(body)
        ] == [
            ("2026-08-03", "candidate", [paired_source], [paired_destination]),
            ("2026-08-10", "unpaired", [lonely], []),
            ("2026-08-17", "ambiguous", sorted(crowded), [crowded_destination]),
        ]
        first_day = _days(body)[0]
        assert first_day["differing_fields"] == ["title"]
        assert first_day["skip_reason"] is None
        journals = body["data"]["attributes"]["journals"]
        assert journals[str(paired_source)]["title"] == "Old"
        assert journals[str(paired_destination)]["title"] == "New"
        assert await series_exists(clean_database, source)
        assert await member_ids(clean_database, destination) == {
            paired_destination,
            crowded_destination,
        }

    async def test_pairs_by_the_users_local_day(
        self,
        integration_api_client: AsyncClient,
        clean_database: AsyncConnection,
        user_settings_repository: Any,
    ) -> None:
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Australia/Sydney")
        )
        source = await seed_series(clean_database, "Old standup")
        destination = await seed_series(clean_database, "Standup")
        # 20:00 UTC on the 2nd is 06:00 on the 3rd in Sydney.
        await seed_member(clean_database, source, title="Old", start=_at(2, 20))
        await seed_member(clean_database, destination, title="New", start=_at(3, 1))

        response = await integration_api_client.post(
            _preview_url(destination), json=_merge_body(source)
        )

        assert response.status_code == 200
        assert [(d["date"], d["kind"]) for d in _days(response.json())] == [
            ("2026-08-03", "candidate")
        ]

    async def test_skip_if_different_policy_reports_the_reason(
        self, integration_api_client: AsyncClient, clean_database: AsyncConnection
    ) -> None:
        source = await seed_series(clean_database, "Old standup")
        destination = await seed_series(clean_database, "Standup")
        await seed_member(clean_database, source, title="Old", start=_at(3, 9))
        await seed_member(clean_database, destination, title="New", start=_at(3, 9))

        response = await integration_api_client.post(
            _preview_url(destination),
            json=_merge_body(source, {"title": "skip_if_different"}),
        )

        assert response.status_code == 200
        [day] = _days(response.json())
        assert day["kind"] == "skipped"
        assert day["skip_reason"] == "title"

    async def test_combine_is_rejected_for_fields_other_than_content(
        self, integration_api_client: AsyncClient, clean_database: AsyncConnection
    ) -> None:
        source = await seed_series(clean_database, "Old standup")
        destination = await seed_series(clean_database, "Standup")

        response = await integration_api_client.post(
            _preview_url(destination), json=_merge_body(source, {"title": "combine"})
        )

        assert response.status_code == 400

    @pytest.mark.parametrize(
        "mistype",
        [
            # A misspelt policy field would otherwise preview the defaults.
            lambda body: body["data"]["attributes"]["policies"].update(
                {"event-description": "skip_if_different"}
            ),
            lambda body: body["data"]["attributes"].update({"policy": {}}),
            lambda body: body["data"].update({"id": "x"}),
            lambda body: body.update({"meta": {}}),
        ],
        ids=["policy-field", "attribute", "data-member", "envelope-member"],
    )
    async def test_unknown_fields_are_refused_at_every_level(
        self,
        integration_api_client: AsyncClient,
        clean_database: AsyncConnection,
        mistype: Any,
    ) -> None:
        source = await seed_series(clean_database, "Old standup")
        destination = await seed_series(clean_database, "Standup")
        body = _merge_body(source, {"title": "source"})
        mistype(body)

        response = await integration_api_client.post(
            _preview_url(destination), json=body
        )

        assert response.status_code == 400

    async def test_merging_a_series_into_itself_is_rejected(
        self, integration_api_client: AsyncClient, clean_database: AsyncConnection
    ) -> None:
        series = await seed_series(clean_database, "Standup")

        response = await integration_api_client.post(
            _preview_url(series), json=_merge_body(series)
        )

        assert response.status_code == 400

    async def test_another_users_source_series_is_not_found(
        self, integration_api_client: AsyncClient, clean_database: AsyncConnection
    ) -> None:
        foreign = await seed_series(clean_database, "Theirs", user_id=OTHER_USER_ID)
        destination = await seed_series(clean_database, "Standup")

        response = await integration_api_client.post(
            _preview_url(destination), json=_merge_body(foreign)
        )

        assert response.status_code == 404

    async def test_another_users_destination_series_is_not_found(
        self, integration_api_client: AsyncClient, clean_database: AsyncConnection
    ) -> None:
        source = await seed_series(clean_database, "Mine")
        foreign = await seed_series(clean_database, "Theirs", user_id=OTHER_USER_ID)

        response = await integration_api_client.post(
            _preview_url(foreign), json=_merge_body(source)
        )

        assert response.status_code == 404
