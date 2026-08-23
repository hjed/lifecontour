"""Integration tests for conditional writes over HTTP (``ETag`` / ``If-Match``).

The precondition itself is tested at the service layer, where it lives; this
suite covers the HTTP contract on top of it — that a read hands out a tag, that
the header is parsed and honoured on the update routes, and that a refusal
comes back as a JSON:API 412 a client can recover from.

A concurrent writer is simulated by nudging the row's ``updated_at``: the test
fixture runs every request inside one shared transaction and Postgres' ``now()``
is the transaction timestamp, so a second real write would not move the tag
here the way it does in production.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

STALE_ETAG = '"0000000000000000"'


def journal_payload(title: str = "Original title") -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "data": {
            "type": "journals",
            "attributes": {
                "title": title,
                "content": "Original content",
                "event_date_range": {"start": now, "end": now},
            },
        }
    }


def contact_payload(first_name: str = "Ada") -> dict[str, Any]:
    return {
        "data": {
            "type": "contacts",
            "attributes": {
                "first_name": first_name,
                "last_name": "Lovelace",
                "contact_methods": [],
                "addresses": [],
                "notes": [],
            },
        }
    }


async def simulate_concurrent_write(
    connection: AsyncConnection, table: str, row_id: str
) -> None:
    """Move a row's ``updated_at`` on, as another writer's commit would."""
    await connection.execute(
        text(
            f"UPDATE {table} SET updated_at = updated_at + interval '1 second' "  # noqa: S608 - fixed table names
            "WHERE id = :row_id"
        ),
        {"row_id": int(row_id)},
    )


@pytest.mark.integration
class TestJournalConditionalWrites:
    """``PUT`` / ``PATCH /api/journals/{id}`` under ``If-Match``."""

    async def test_get_hands_out_an_etag(self, integration_api_client):
        created = await integration_api_client.post(
            "/api/journals", json=journal_payload()
        )
        journal_id = created.json()["data"]["id"]

        response = await integration_api_client.get(f"/api/journals/{journal_id}")

        assert response.status_code == 200
        assert response.headers["ETag"].startswith('"')

    async def test_the_etag_is_readable_from_an_allowed_origin(
        self, integration_api_client
    ):
        """``ETag`` is not CORS-safelisted, so it must be exposed explicitly.

        A browser client at an allowed origin that cannot *read* the tag cannot
        send it back in ``If-Match`` either, which would leave the whole
        conditional-write flow advertised but unusable off-origin.
        """
        created = await integration_api_client.post(
            "/api/journals", json=journal_payload()
        )
        journal_id = created.json()["data"]["id"]

        response = await integration_api_client.get(
            f"/api/journals/{journal_id}",
            headers={"Origin": "https://app.example.com"},
        )

        exposed = response.headers.get("access-control-expose-headers", "")
        assert "etag" in exposed.lower()

    async def test_update_echoes_the_new_etag(self, integration_api_client):
        """A writer can chain edits without re-reading the resource."""
        created = await integration_api_client.post(
            "/api/journals", json=journal_payload()
        )
        journal_id = created.json()["data"]["id"]

        payload = journal_payload(title="Updated title")
        payload["data"]["id"] = journal_id
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}", json=payload
        )

        assert response.status_code == 200
        assert response.headers["ETag"].startswith('"')

    async def test_matching_if_match_is_written(self, integration_api_client):
        created = await integration_api_client.post(
            "/api/journals", json=journal_payload()
        )
        journal_id = created.json()["data"]["id"]
        etag = (
            await integration_api_client.get(f"/api/journals/{journal_id}")
        ).headers["ETag"]

        payload = journal_payload(title="Updated title")
        payload["data"]["id"] = journal_id
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}", json=payload, headers={"If-Match": etag}
        )

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["title"] == "Updated title"

    async def test_a_tag_on_a_later_header_line_still_matches(
        self, integration_api_client
    ):
        """``If-Match`` is a list field, so HTTP lets it span repeated lines.

        Reading only the first line would 412 a request whose matching tag
        arrived on a later one — the opposite of any-tag-matches.
        """
        created = await integration_api_client.post(
            "/api/journals", json=journal_payload()
        )
        journal_id = created.json()["data"]["id"]
        etag = (
            await integration_api_client.get(f"/api/journals/{journal_id}")
        ).headers["ETag"]

        payload = journal_payload(title="Updated title")
        payload["data"]["id"] = journal_id
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}",
            json=payload,
            headers=[("If-Match", STALE_ETAG), ("If-Match", etag)],
        )

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["title"] == "Updated title"

    async def test_stale_if_match_is_refused(
        self, integration_api_client, async_connection
    ):
        created = await integration_api_client.post(
            "/api/journals", json=journal_payload()
        )
        journal_id = created.json()["data"]["id"]
        stale_etag = (
            await integration_api_client.get(f"/api/journals/{journal_id}")
        ).headers["ETag"]
        await simulate_concurrent_write(async_connection, "journals", journal_id)

        payload = journal_payload(title="Updated title")
        payload["data"]["id"] = journal_id
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}",
            json=payload,
            headers={"If-Match": stale_etag},
        )

        assert response.status_code == 412
        error = response.json()["errors"][0]
        assert error["code"] == "PRECONDITION_FAILED"
        # The current tag travels with the refusal so a client can re-read and
        # retry without a second round trip to discover what it should send.
        current_etag = (
            await integration_api_client.get(f"/api/journals/{journal_id}")
        ).headers["ETag"]
        assert error["meta"]["current_etag"] == current_etag

    async def test_refused_update_leaves_the_journal_alone(
        self, integration_api_client, async_connection
    ):
        created = await integration_api_client.post(
            "/api/journals", json=journal_payload()
        )
        journal_id = created.json()["data"]["id"]
        stale_etag = (
            await integration_api_client.get(f"/api/journals/{journal_id}")
        ).headers["ETag"]
        await simulate_concurrent_write(async_connection, "journals", journal_id)

        payload = journal_payload(title="Updated title")
        payload["data"]["id"] = journal_id
        await integration_api_client.put(
            f"/api/journals/{journal_id}",
            json=payload,
            headers={"If-Match": stale_etag},
        )

        after = await integration_api_client.get(f"/api/journals/{journal_id}")
        assert after.json()["data"]["attributes"]["title"] == "Original title"

    async def test_patch_honours_if_match(
        self, integration_api_client, async_connection
    ):
        """The partial-update route is guarded too, not just the full replace."""
        created = await integration_api_client.post(
            "/api/journals", json=journal_payload()
        )
        journal_id = created.json()["data"]["id"]
        stale_etag = (
            await integration_api_client.get(f"/api/journals/{journal_id}")
        ).headers["ETag"]
        await simulate_concurrent_write(async_connection, "journals", journal_id)

        response = await integration_api_client.patch(
            f"/api/journals/{journal_id}",
            json={
                "data": {
                    "type": "journals",
                    "id": journal_id,
                    "attributes": {"title": "Updated title"},
                }
            },
            headers={"If-Match": stale_etag},
        )

        assert response.status_code == 412

    async def test_no_if_match_writes_as_before(
        self, integration_api_client, async_connection
    ):
        """Existing clients send no precondition and must be unaffected."""
        created = await integration_api_client.post(
            "/api/journals", json=journal_payload()
        )
        journal_id = created.json()["data"]["id"]
        await simulate_concurrent_write(async_connection, "journals", journal_id)

        payload = journal_payload(title="Updated title")
        payload["data"]["id"] = journal_id
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}", json=payload
        )

        assert response.status_code == 200

    async def test_wildcard_if_match_writes_at_any_version(
        self, integration_api_client, async_connection
    ):
        created = await integration_api_client.post(
            "/api/journals", json=journal_payload()
        )
        journal_id = created.json()["data"]["id"]
        await simulate_concurrent_write(async_connection, "journals", journal_id)

        payload = journal_payload(title="Updated title")
        payload["data"]["id"] = journal_id
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}", json=payload, headers={"If-Match": "*"}
        )

        assert response.status_code == 200

    async def test_absent_journal_is_404_not_412(self, integration_api_client):
        """Existence is settled before the precondition, so the 404 still wins."""
        payload = journal_payload(title="Updated title")
        payload["data"]["id"] = "999999"

        response = await integration_api_client.put(
            "/api/journals/999999", json=payload, headers={"If-Match": STALE_ETAG}
        )

        assert response.status_code == 404


@pytest.mark.integration
class TestContactConditionalWrites:
    """``PUT /api/contacts/{id}`` under ``If-Match``."""

    async def test_get_hands_out_an_etag(self, integration_api_client):
        created = await integration_api_client.post(
            "/api/contacts", json=contact_payload()
        )
        contact_id = created.json()["data"]["id"]

        response = await integration_api_client.get(f"/api/contacts/{contact_id}")

        assert response.status_code == 200
        assert response.headers["ETag"].startswith('"')

    async def test_matching_if_match_is_written(self, integration_api_client):
        created = await integration_api_client.post(
            "/api/contacts", json=contact_payload()
        )
        contact_id = created.json()["data"]["id"]
        etag = (
            await integration_api_client.get(f"/api/contacts/{contact_id}")
        ).headers["ETag"]

        payload = contact_payload(first_name="Augusta")
        payload["data"]["id"] = contact_id
        response = await integration_api_client.put(
            f"/api/contacts/{contact_id}", json=payload, headers={"If-Match": etag}
        )

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["first_name"] == "Augusta"

    async def test_stale_if_match_is_refused(
        self, integration_api_client, async_connection
    ):
        created = await integration_api_client.post(
            "/api/contacts", json=contact_payload()
        )
        contact_id = created.json()["data"]["id"]
        stale_etag = (
            await integration_api_client.get(f"/api/contacts/{contact_id}")
        ).headers["ETag"]
        await simulate_concurrent_write(async_connection, "contacts", contact_id)

        payload = contact_payload(first_name="Augusta")
        payload["data"]["id"] = contact_id
        response = await integration_api_client.put(
            f"/api/contacts/{contact_id}",
            json=payload,
            headers={"If-Match": stale_etag},
        )

        assert response.status_code == 412
        assert response.json()["errors"][0]["code"] == "PRECONDITION_FAILED"
        after = await integration_api_client.get(f"/api/contacts/{contact_id}")
        assert after.json()["data"]["attributes"]["first_name"] == "Ada"

    async def test_no_if_match_writes_as_before(
        self, integration_api_client, async_connection
    ):
        created = await integration_api_client.post(
            "/api/contacts", json=contact_payload()
        )
        contact_id = created.json()["data"]["id"]
        await simulate_concurrent_write(async_connection, "contacts", contact_id)

        payload = contact_payload(first_name="Augusta")
        payload["data"]["id"] = contact_id
        response = await integration_api_client.put(
            f"/api/contacts/{contact_id}", json=payload
        )

        assert response.status_code == 200


@pytest.mark.integration
class TestTheTagCoversTheWholeJournal:
    """A read returns the journal *aggregate*, so its tag must track all of it.

    Types, type-specific data, tags and contact relationships all appear in
    ``GET /api/journals/{id}``. A write to any of them that left
    ``journals.updated_at`` alone would leave the tag naming a version that no
    longer describes what a client would read — and the MCP composite update
    *replaces* those collections under the caller's precondition, so the
    concurrent change it was meant to catch would be clobbered instead.

    ``now()`` is the transaction timestamp and this fixture shares one
    transaction, so "the timestamp went up" cannot be asserted here. Each test
    instead backdates the row to a fixed instant and asserts the write moved it
    off that instant — which is exactly the touch, and is deterministic.
    """

    BACKDATED = datetime(2000, 1, 1, tzinfo=UTC)

    async def _backdate(self, connection: AsyncConnection, journal_id: str) -> None:
        await connection.execute(
            text("UPDATE journals SET updated_at = :ts WHERE id = :row_id"),
            {"ts": self.BACKDATED, "row_id": int(journal_id)},
        )

    async def _updated_at(
        self, connection: AsyncConnection, journal_id: str
    ) -> datetime:
        result = await connection.execute(
            text("SELECT updated_at FROM journals WHERE id = :row_id"),
            {"row_id": int(journal_id)},
        )
        stored: datetime = result.scalar_one()
        return stored

    async def _create_journal(self, client) -> str:
        created = await client.post("/api/journals", json=journal_payload())
        return str(created.json()["data"]["id"])

    async def test_adding_a_tag_moves_the_version(
        self, integration_api_client, async_connection
    ):
        journal_id = await self._create_journal(integration_api_client)
        tag = await integration_api_client.post(
            "/api/journals/tags",
            json={"data": {"type": "journal-tags", "attributes": {"name": "outdoors"}}},
        )
        tag_id = tag.json()["data"]["id"]
        await self._backdate(async_connection, journal_id)

        response = await integration_api_client.post(
            f"/api/journals/{journal_id}/relationships/tags",
            json={"data": {"type": "journal-tag", "attributes": {"tag_id": tag_id}}},
        )

        assert response.status_code in (200, 201, 204)
        assert await self._updated_at(async_connection, journal_id) != self.BACKDATED

    async def test_updating_type_data_moves_the_version(
        self, integration_api_client, async_connection
    ):
        payload = journal_payload()
        payload["data"]["attributes"]["types"] = ["MOOD_RATING"]
        created = await integration_api_client.post("/api/journals", json=payload)
        journal_id = str(created.json()["data"]["id"])
        await self._backdate(async_connection, journal_id)

        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/MOOD_RATING/data",
            json={
                "data": {"type": "journal-type-data", "attributes": {"mood_value": 7}}
            },
        )

        assert response.status_code == 200
        assert await self._updated_at(async_connection, journal_id) != self.BACKDATED

    async def test_adding_a_type_moves_the_version(
        self, integration_api_client, async_connection
    ):
        journal_id = await self._create_journal(integration_api_client)
        await self._backdate(async_connection, journal_id)

        response = await integration_api_client.post(
            f"/api/journals/{journal_id}/types",
            json={
                "data": {
                    "type": "journal-type",
                    "attributes": {"journal_type": "MOOD_RATING"},
                }
            },
        )

        assert response.status_code in (200, 201, 204)
        assert await self._updated_at(async_connection, journal_id) != self.BACKDATED

    async def test_linking_a_contact_moves_the_version(
        self, integration_api_client, async_connection
    ):
        journal_id = await self._create_journal(integration_api_client)
        contact = await integration_api_client.post(
            "/api/contacts", json=contact_payload()
        )
        contact_id = contact.json()["data"]["id"]
        await self._backdate(async_connection, journal_id)

        response = await integration_api_client.post(
            f"/api/journals/{journal_id}/relationships/contacts",
            json={
                "data": {
                    "type": "journal-contact-relationships",
                    "attributes": {
                        "contact_id": str(contact_id),
                        "relationship_type": "PARTICIPANT",
                    },
                }
            },
        )

        assert response.status_code in (200, 201, 204)
        assert await self._updated_at(async_connection, journal_id) != self.BACKDATED

    async def _create_tag(self, client, name: str) -> str:
        created = await client.post(
            "/api/journals/tags",
            json={"data": {"type": "journal-tags", "attributes": {"name": name}}},
        )
        return str(created.json()["data"]["id"])

    async def _assign_tag(self, client, journal_id: str, tag_id: str) -> None:
        await client.post(
            f"/api/journals/{journal_id}/relationships/tags",
            json={"data": {"type": "journal-tag", "attributes": {"tag_id": tag_id}}},
        )

    async def test_merging_a_tag_moves_the_version_of_every_journal_holding_it(
        self, integration_api_client, async_connection
    ):
        """A bulk assignment rewrite changes journals the caller never names.

        The journals are found from the assignments themselves, before the
        rewrite stops those rows pointing at the source tag.
        """
        journal_id = await self._create_journal(integration_api_client)
        source = await self._create_tag(integration_api_client, "source-tag")
        target = await self._create_tag(integration_api_client, "target-tag")
        await self._assign_tag(integration_api_client, journal_id, source)
        await self._backdate(async_connection, journal_id)

        response = await integration_api_client.post(
            f"/api/journals/tags/{source}/merge",
            json={
                "data": {
                    "type": "journal-tags",
                    "attributes": {"target_tag_id": target},
                }
            },
        )

        assert response.status_code in (200, 201, 204)
        assert await self._updated_at(async_connection, journal_id) != self.BACKDATED

    async def test_deleting_a_tag_moves_the_version_of_every_journal_holding_it(
        self, integration_api_client, async_connection
    ):
        """The assignments go by ``ON DELETE CASCADE``, which no code path sees."""
        journal_id = await self._create_journal(integration_api_client)
        tag_id = await self._create_tag(integration_api_client, "doomed-tag")
        await self._assign_tag(integration_api_client, journal_id, tag_id)
        await self._backdate(async_connection, journal_id)

        response = await integration_api_client.delete(f"/api/journals/tags/{tag_id}")

        assert response.status_code in (200, 204)
        assert await self._updated_at(async_connection, journal_id) != self.BACKDATED
