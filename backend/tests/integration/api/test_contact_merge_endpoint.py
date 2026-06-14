"""Integration tests for the contact merge endpoint (ITER13-001 Phase 3).

Exercises ``POST /api/contacts/{id}/merge`` end-to-end: the survivor absorbs the
source's aggregate (deduplicated), scalar fields resolve survivor-wins /
prefer-non-empty, the source is deleted, and validation errors map to the
correct status codes. The merge engine itself (re-points / dedupe constraints)
is covered by the service- and repository-level integration tests; here we
verify the HTTP surface is wired correctly.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection


async def _create_contact(client: AsyncClient, attributes: dict[str, Any]) -> int:
    """Create a contact via the API and return its integer id."""
    base = {
        "first_name": "Test",
        "contact_methods": [],
        "addresses": [],
        "notes": [],
    }
    base.update(attributes)
    res = await client.post(
        "/api/contacts",
        json={"data": {"type": "contacts", "attributes": base}},
    )
    assert res.status_code == 201, res.text
    return int(res.json()["data"]["id"])


def _phone(value: str, *, is_primary: bool = False) -> dict[str, Any]:
    return {
        "type": "contact_methods",
        "attributes": {
            "method_type": "phone",
            "value": value,
            "label": "Mobile",
            "is_primary": is_primary,
        },
    }


@pytest.mark.asyncio
async def test_merge_contact_endpoint_consolidates_and_deletes_source(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """Survivor keeps both contacts' methods, fills empty scalars, source is gone."""
    survivor_id = await _create_contact(
        authenticated_client,
        {
            "first_name": "Jane",
            "last_name": "Survivor",
            "middle_name": None,
            "contact_methods": [_phone("+61-2-0000-0001", is_primary=True)],
        },
    )
    source_id = await _create_contact(
        authenticated_client,
        {
            "first_name": "Janet",
            "last_name": "Source",
            "middle_name": "Mariposa",
            "contact_methods": [_phone("+61-2-0000-0002")],
        },
    )

    merge_res = await authenticated_client.post(
        f"/api/contacts/{survivor_id}/merge",
        json={
            "data": {
                "type": "contact-merge",
                "attributes": {"source_contact_id": source_id},
            }
        },
    )

    assert merge_res.status_code == 200, merge_res.text
    attrs = merge_res.json()["data"]["attributes"]
    # Survivor identity wins where both differ.
    assert attrs["first_name"] == "Jane"
    assert attrs["last_name"] == "Survivor"
    # Prefer-non-empty fills the survivor's empty middle_name from the source.
    assert attrs["middle_name"] == "Mariposa"
    # Both phone methods carry over, deduplicated by value (two distinct).
    phones = {
        m["attributes"]["value"]
        for m in attrs["contact_methods"]
        if m["attributes"]["method_type"] == "phone"
    }
    assert phones == {"+61-2-0000-0001", "+61-2-0000-0002"}

    # The source contact is deleted after a successful merge.
    get_source = await authenticated_client.get(f"/api/contacts/{source_id}")
    assert get_source.status_code == 404


@pytest.mark.asyncio
async def test_merge_contact_endpoint_dedupes_journal_links(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """A journal linked to both contacts with the same role collapses to one link."""
    survivor_id = await _create_contact(authenticated_client, {"first_name": "Keep"})
    source_id = await _create_contact(authenticated_client, {"first_name": "Absorb"})

    journal_res = await authenticated_client.post(
        "/api/journals",
        json={
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Shared Journal",
                    "content": "Body",
                    "event_date_range": {
                        "start": "2024-01-01T00:00:00Z",
                        "end": "2024-01-01T01:00:00Z",
                    },
                },
            }
        },
    )
    assert journal_res.status_code == 201, journal_res.text
    journal_id = int(journal_res.json()["data"]["id"])

    for contact_id in (survivor_id, source_id):
        link_res = await authenticated_client.post(
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
        assert link_res.status_code == 200, link_res.text

    merge_res = await authenticated_client.post(
        f"/api/contacts/{survivor_id}/merge",
        json={
            "data": {
                "type": "contact-merge",
                "attributes": {"source_contact_id": source_id},
            }
        },
    )
    assert merge_res.status_code == 200, merge_res.text

    journals_res = await authenticated_client.get(
        f"/api/contacts/{survivor_id}/journals?relationship_type=PARTICIPANT"
    )
    assert journals_res.status_code == 200, journals_res.text
    linked = journals_res.json()["data"]
    assert len([j for j in linked if int(j["id"]) == journal_id]) == 1


@pytest.mark.asyncio
async def test_merge_contact_endpoint_applies_field_overrides(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """ITER13-002: per-field overrides apply survivor / source / custom end-to-end.

    Asserts the converter-exposed identity fields (``nick_name``, ``middle_name``,
    ``is_favourite``) via the HTTP response and the non-exposed ``company`` field
    directly in the database, so the full HTTP -> service -> DB path is verified.
    """
    survivor_id = await _create_contact(
        authenticated_client,
        {
            "first_name": "Jane",
            "last_name": "Survivor",
            "nick_name": "Survivor Nick",
            "middle_name": "SurvivorMiddle",
            "company": "SurvivorCo",
            "is_favourite": True,
        },
    )
    source_id = await _create_contact(
        authenticated_client,
        {
            "first_name": "Janet",
            "last_name": "Source",
            "nick_name": "Source Nick",
            "middle_name": "SourceMiddle",
            "company": "SourceCo",
        },
    )

    merge_res = await authenticated_client.post(
        f"/api/contacts/{survivor_id}/merge",
        json={
            "data": {
                "type": "contact-merge",
                "attributes": {
                    "source_contact_id": source_id,
                    "overrides": {
                        # take the source value for nick_name
                        "nick_name": "Source Nick",
                        # supply a custom value for middle_name
                        "middle_name": "Custom Middle",
                        # take the source value for company
                        "company": "SourceCo",
                        # explicitly clear the survivor's favourite flag
                        "is_favourite": False,
                    },
                },
            }
        },
    )

    assert merge_res.status_code == 200, merge_res.text
    attrs = merge_res.json()["data"]["attributes"]
    # last_name has no override -> survivor wins by default.
    assert attrs["last_name"] == "Survivor"
    # nick_name override picks the source's value over the survivor's.
    assert attrs["nick_name"] == "Source Nick"
    # middle_name override applies a custom value.
    assert attrs["middle_name"] == "Custom Middle"
    # is_favourite override is honoured even though it is falsy.
    assert attrs["is_favourite"] is False

    # company is not exposed by the REST converter — verify it in the database.
    from sqlalchemy import text

    company_row = await async_connection.execute(
        text("SELECT company FROM contacts WHERE id = :id"), {"id": survivor_id}
    )
    assert company_row.scalar_one() == "SourceCo"

    get_source = await authenticated_client.get(f"/api/contacts/{source_id}")
    assert get_source.status_code == 404


@pytest.mark.asyncio
async def test_merge_contact_self_merge_returns_409(
    authenticated_client: AsyncClient,
    clean_database: None,
) -> None:
    """Merging a contact into itself is a conflict."""
    contact_id = await _create_contact(authenticated_client, {"first_name": "Solo"})

    res = await authenticated_client.post(
        f"/api/contacts/{contact_id}/merge",
        json={
            "data": {
                "type": "contact-merge",
                "attributes": {"source_contact_id": contact_id},
            }
        },
    )
    assert res.status_code == 409, res.text


@pytest.mark.asyncio
async def test_merge_contact_missing_source_returns_404(
    authenticated_client: AsyncClient,
    clean_database: None,
) -> None:
    """A missing source contact yields a 404."""
    survivor_id = await _create_contact(
        authenticated_client, {"first_name": "Survivor"}
    )

    res = await authenticated_client.post(
        f"/api/contacts/{survivor_id}/merge",
        json={
            "data": {
                "type": "contact-merge",
                "attributes": {"source_contact_id": 999999},
            }
        },
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_merge_contact_missing_survivor_returns_404(
    authenticated_client: AsyncClient,
    clean_database: None,
) -> None:
    """A missing survivor contact yields a 404."""
    source_id = await _create_contact(authenticated_client, {"first_name": "Source"})

    res = await authenticated_client.post(
        "/api/contacts/999999/merge",
        json={
            "data": {
                "type": "contact-merge",
                "attributes": {"source_contact_id": source_id},
            }
        },
    )
    assert res.status_code == 404, res.text
