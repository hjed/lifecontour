"""Integration tests for merging one journal series into another over REST."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_series_repository import (
    SqlJournalSeriesRepository,
)
from app.core.settings.models import UserSettings
from tests.integration.linked_calendar_seeding import link_calendar
from tests.integration.series_merge_seeding import (
    OTHER_USER_ID,
    USER_ID,
    journal_exists,
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

    async def test_a_different_resource_type_is_refused(
        self, integration_api_client: AsyncClient, clean_database: AsyncConnection
    ) -> None:
        source = await seed_series(clean_database, "Old standup")
        destination = await seed_series(clean_database, "Standup")
        body = _merge_body(source)
        body["data"]["type"] = "journals"

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


def _execute_body(
    source_series_id: uuid.UUID,
    pairs: list[tuple[int, int]],
    policies: dict[str, str] | None = None,
) -> dict[str, Any]:
    body = _merge_body(source_series_id, policies)
    body["data"]["attributes"]["pairs"] = [
        {"source_journal_id": s, "destination_journal_id": d} for s, d in pairs
    ]
    return body


def _merge_url(destination_series_id: uuid.UUID) -> str:
    return f"/api/journals/series/{destination_series_id}/merge"


async def _title(connection: AsyncConnection, journal_id: int) -> str:
    result = await connection.execute(
        text("SELECT title FROM journals WHERE id = :id"), {"id": journal_id}
    )
    title: str = result.scalar_one()
    return title


@pytest.mark.integration
class TestMergeSeries:
    async def test_merges_confirmed_pairs_and_absorbs_the_source_series(
        self, integration_api_client: AsyncClient, clean_database: AsyncConnection
    ) -> None:
        calendar = await seed_calendar(clean_database)
        source = await seed_series(clean_database, "Old standup")
        destination = await seed_series(clean_database, "Standup")
        paired_source = await seed_member(
            clean_database,
            source,
            title="Old",
            start=_at(3, 9),
            calendar_id=calendar,
            location="Room 1",
        )
        paired_destination = await seed_member(
            clean_database, destination, title="New", start=_at(3, 9)
        )
        lonely = await seed_member(
            clean_database, source, title="Old", start=_at(10, 9)
        )

        response = await integration_api_client.post(
            _merge_url(destination),
            json=_execute_body(
                source, [(paired_source, paired_destination)], {"title": "source"}
            ),
        )

        assert response.status_code == 200
        assert [(d["date"], d["kind"]) for d in _days(response.json())] == [
            ("2026-08-03", "merged"),
            ("2026-08-10", "unpaired"),
        ]
        assert not await journal_exists(clean_database, paired_source)
        assert await _title(clean_database, paired_destination) == "Old"
        assert await member_ids(clean_database, destination) == {
            paired_destination,
            lonely,
        }
        assert not await series_exists(clean_database, source)

    async def test_a_same_calendar_pair_merges_and_keeps_the_targets_link(
        self, integration_api_client: AsyncClient, clean_database: AsyncConnection
    ) -> None:
        calendar = await seed_calendar(clean_database)
        source = await seed_series(clean_database, "Old standup")
        destination = await seed_series(clean_database, "Standup")
        paired_source = await seed_member(
            clean_database, source, title="Old", start=_at(3, 9), calendar_id=calendar
        )
        paired_destination = await seed_member(
            clean_database,
            destination,
            title="New",
            start=_at(3, 9),
            calendar_id=calendar,
        )
        await link_calendar(
            clean_database,
            journal_id=paired_source,
            calendar_id=str(calendar),
            external_event_id="old-instance",
        )
        await link_calendar(
            clean_database,
            journal_id=paired_destination,
            calendar_id=str(calendar),
            external_event_id="new-instance",
        )

        response = await integration_api_client.post(
            _merge_url(destination),
            json=_execute_body(source, [(paired_source, paired_destination)]),
        )

        assert response.status_code == 200
        assert [d["kind"] for d in _days(response.json())] == ["merged"]
        links = await clean_database.execute(
            text(
                "SELECT external_event_id FROM journal_external_event_links"
                " WHERE journal_id = :id"
            ),
            {"id": paired_destination},
        )
        assert [row.external_event_id for row in links] == ["new-instance"]

    async def test_unconfirmed_and_skipped_pairs_are_kept_and_join_the_destination(
        self, integration_api_client: AsyncClient, clean_database: AsyncConnection
    ) -> None:
        source = await seed_series(clean_database, "Old standup")
        destination = await seed_series(clean_database, "Standup")
        unticked = await seed_member(
            clean_database, source, title="Standup", start=_at(3, 9)
        )
        unticked_partner = await seed_member(
            clean_database, destination, title="Standup", start=_at(3, 9)
        )
        different = await seed_member(
            clean_database, source, title="Old", start=_at(10, 9)
        )
        different_partner = await seed_member(
            clean_database, destination, title="New", start=_at(10, 9)
        )

        response = await integration_api_client.post(
            _merge_url(destination),
            json=_execute_body(source, [], {"title": "skip_if_different"}),
        )

        assert response.status_code == 200
        assert [d["kind"] for d in _days(response.json())] == ["excluded", "skipped"]
        assert await member_ids(clean_database, destination) == {
            unticked,
            unticked_partner,
            different,
            different_partner,
        }
        assert not await series_exists(clean_database, source)

    async def test_a_pair_that_is_no_longer_a_candidate_is_refused(
        self, integration_api_client: AsyncClient, clean_database: AsyncConnection
    ) -> None:
        source = await seed_series(clean_database, "Old standup")
        destination = await seed_series(clean_database, "Standup")
        source_journal = await seed_member(
            clean_database, source, title="Old", start=_at(3, 9)
        )
        # Previewed on the 3rd; moved to the 4th before the merge was sent.
        destination_journal = await seed_member(
            clean_database, destination, title="New", start=_at(4, 9)
        )

        response = await integration_api_client.post(
            _merge_url(destination),
            json=_execute_body(source, [(source_journal, destination_journal)]),
        )

        assert response.status_code == 409
        assert await series_exists(clean_database, source)
        assert await journal_exists(clean_database, source_journal)
        assert await member_ids(clean_database, destination) == {destination_journal}

    async def test_a_failing_pair_rolls_back_alone(
        self, integration_api_client: AsyncClient, clean_database: AsyncConnection
    ) -> None:
        source = await seed_series(clean_database, "Old standup")
        destination = await seed_series(clean_database, "Standup")
        parent = await seed_member(clean_database, source, title="Old", start=_at(3, 9))
        child = await seed_member(
            clean_database, destination, title="New", start=_at(3, 9)
        )
        # A journal cannot absorb its own ancestor: this pair's merge raises.
        await clean_database.execute(
            text("UPDATE journals SET parent_id = :parent WHERE id = :child"),
            {"parent": parent, "child": child},
        )
        good_source = await seed_member(
            clean_database, source, title="Old", start=_at(10, 9)
        )
        good_destination = await seed_member(
            clean_database, destination, title="New", start=_at(10, 9)
        )

        response = await integration_api_client.post(
            _merge_url(destination),
            json=_execute_body(
                source, [(parent, child), (good_source, good_destination)]
            ),
        )

        assert response.status_code == 200
        assert [d["kind"] for d in _days(response.json())] == ["failed", "merged"]
        assert await journal_exists(clean_database, parent)
        assert not await journal_exists(clean_database, good_source)
        assert await member_ids(clean_database, destination) == {
            parent,
            child,
            good_destination,
        }

    @pytest.mark.parametrize(
        "mistype",
        [
            # A misspelt ``pairs`` would otherwise merge no pair at all.
            lambda body: body["data"]["attributes"].update(
                {"pair": body["data"]["attributes"].pop("pairs")}
            ),
            lambda body: body["data"]["attributes"]["pairs"][0].update(
                {"target_journal_id": 0}
            ),
            lambda body: body["data"].update({"id": "x"}),
            lambda body: body.update({"meta": {}}),
        ],
        ids=["attribute", "pair-member", "data-member", "envelope-member"],
    )
    async def test_unknown_fields_are_refused_and_nothing_is_written(
        self,
        integration_api_client: AsyncClient,
        clean_database: AsyncConnection,
        mistype: Any,
    ) -> None:
        source = await seed_series(clean_database, "Old standup")
        destination = await seed_series(clean_database, "Standup")
        source_journal = await seed_member(
            clean_database, source, title="Old", start=_at(3, 9)
        )
        destination_journal = await seed_member(
            clean_database, destination, title="New", start=_at(3, 9)
        )
        body = _execute_body(source, [(source_journal, destination_journal)])
        mistype(body)

        response = await integration_api_client.post(_merge_url(destination), json=body)

        assert response.status_code == 400
        assert await series_exists(clean_database, source)
        assert await journal_exists(clean_database, source_journal)

    async def test_a_different_resource_type_is_refused_and_nothing_is_written(
        self, integration_api_client: AsyncClient, clean_database: AsyncConnection
    ) -> None:
        source = await seed_series(clean_database, "Old standup")
        destination = await seed_series(clean_database, "Standup")
        body = _execute_body(source, [])
        body["data"]["type"] = "journals"

        response = await integration_api_client.post(_merge_url(destination), json=body)

        assert response.status_code == 400
        assert await series_exists(clean_database, source)

    async def test_a_pair_with_one_event_keeps_that_events_timing(
        self, integration_api_client: AsyncClient, clean_database: AsyncConnection
    ) -> None:
        calendar = await seed_calendar(clean_database)
        source = await seed_series(clean_database, "Old standup")
        destination = await seed_series(clean_database, "Standup")
        event = await seed_member(
            clean_database, source, title="Event", start=_at(3, 9), calendar_id=calendar
        )
        await clean_database.execute(
            text(
                "UPDATE journal_calendar_info SET start_time = '19:00',"
                " end_time = '20:00', timezone = 'Australia/Sydney'"
                " WHERE journal_id = :id"
            ),
            {"id": event},
        )
        plain = await seed_member(
            clean_database, destination, title="Note", start=_at(3, 1)
        )

        # The destination's timing is preferred, but it is not an event.
        response = await integration_api_client.post(
            _merge_url(destination),
            json=_execute_body(source, [(event, plain)], {"timing": "destination"}),
        )

        assert response.status_code == 200
        row = (
            await clean_database.execute(
                text(
                    "SELECT j.event_date_range_start, c.start_time, c.end_time,"
                    " c.timezone FROM journals j"
                    " JOIN journal_calendar_info c ON c.journal_id = j.id"
                    " WHERE j.id = :id"
                ),
                {"id": plain},
            )
        ).one()
        assert row.event_date_range_start == _at(3, 9)
        assert (str(row.start_time), str(row.end_time), row.timezone) == (
            "19:00:00",
            "20:00:00",
            "Australia/Sydney",
        )

    async def test_the_source_recurrence_resolves_to_the_destination_afterwards(
        self, integration_api_client: AsyncClient, clean_database: AsyncConnection
    ) -> None:
        calendar = await seed_calendar(clean_database)
        source = await seed_series(
            clean_database,
            "Old standup",
            calendar_id=calendar,
            recurring_event_id="old-master",
        )
        destination = await seed_series(clean_database, "Standup")

        response = await integration_api_client.post(
            _merge_url(destination), json=_execute_body(source, [])
        )

        assert response.status_code == 200
        resolved = await SqlJournalSeriesRepository(
            clean_database
        ).get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=calendar,
            recurring_event_id="old-master",
            name="Must not be created",
        )
        assert resolved.id == destination
