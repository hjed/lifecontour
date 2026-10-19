"""Every write to a contact's rows honours ``If-Match`` and hands back an ``ETag``.

A contact's entity-tag covers the whole aggregate: its methods, addresses,
notes and important dates appear in the representation it is minted from, and
every write to them touches the contact. So a client holding a contact's tag
can guard a write to any one of its rows with it, and each such write answers
with the tag of the version it committed - its next precondition.

Each guarded route is asked three things:

- a matching tag writes, and the ``ETag`` it answers with is the contact's
  current one;
- a stale tag is refused with a JSON:API ``412`` carrying the current tag, and
  **no** row the write could reach has moved;
- ``*`` writes, since it asks only that the contact exist.

Writing without the header is the behaviour every route had before, and is
already proven for each of them by the ownership suite's owner replay.

The requests are the ownership suite's own, made by the owner: each is already
proven valid there, so a refusal here can only be the precondition's.
:class:`TestPreconditionCoverageIsComplete` compares the table with the app's
routes, so a new contact write fails until it is guarded or exempted with a
reason.
"""

from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncConnection

from app.main import create_app
from tests.integration.api.test_contact_ownership import (
    CROSS_USER_REQUESTS,
    CrossUserRequest,
)
from tests.integration.foreign_contact_seeding import (
    ForeignContact,
    hand_foreign_rows_to_caller,
    seed_foreign_contact,
    snapshot,
)

STALE_ETAG = '"0000000000000000"'

CONTACT_ROUTE = "/api/contacts/{contact_id}"
METHOD_ROUTE = CONTACT_ROUTE + "/methods/{method_id}"
ADDRESS_ROUTE = CONTACT_ROUTE + "/addresses/{address_id}"
IMPORTANT_DATE_ROUTE = CONTACT_ROUTE + "/important-dates/{date_id}"
RELATIONSHIPS_ROUTE = CONTACT_ROUTE + "/relationships"

GUARDED: frozenset[tuple[str, str]] = frozenset(
    {
        ("PATCH", CONTACT_ROUTE + "/fields/{field_name}"),
        ("POST", CONTACT_ROUTE + "/methods"),
        ("DELETE", METHOD_ROUTE),
        ("PATCH", METHOD_ROUTE + "/fields/{field_name}"),
        ("POST", CONTACT_ROUTE + "/addresses"),
        ("DELETE", ADDRESS_ROUTE),
        ("PATCH", ADDRESS_ROUTE + "/fields/{field_name}"),
        ("PATCH", CONTACT_ROUTE + "/notes/{note_id}/fields/{field_name}"),
        ("POST", CONTACT_ROUTE + "/important-dates"),
        ("PUT", IMPORTANT_DATE_ROUTE),
        ("DELETE", IMPORTANT_DATE_ROUTE),
    }
)

GUARDED_REQUESTS: tuple[CrossUserRequest, ...] = tuple(
    spec for spec in CROSS_USER_REQUESTS if (spec.method, spec.route) in GUARDED
)

# Contact writes outside the table, each with the reason. Keyed on
# ``(method, path)`` so an exemption cannot quietly cover a verb the path grows.
NOT_A_CHILD_ROW_WRITE = "covered by test_etag_concurrency.py"
OWN_RESOURCE = (
    "not part of the contact's version: it is its own resource, and writing it "
    "does not touch the contact"
)
UNGUARDED_BY_DESIGN: dict[tuple[str, str], str] = {
    ("PUT", CONTACT_ROUTE): NOT_A_CHILD_ROW_WRITE,
    ("DELETE", CONTACT_ROUTE): (
        "removes the whole aggregate: there is no later state for a stale "
        "client to overwrite"
    ),
    ("POST", CONTACT_ROUTE + "/merge"): (
        "writes two aggregates under the merge's own lock protocol "
        "(both contacts FOR UPDATE in id order)"
    ),
    ("PATCH", CONTACT_ROUTE + "/summary"): OWN_RESOURCE,
    ("POST", CONTACT_ROUTE + "/summary/refresh"): (
        "asynchronous (202): requests a regeneration and writes nothing itself"
    ),
    ("POST", RELATIONSHIPS_ROUTE): OWN_RESOURCE,
    ("PUT", RELATIONSHIPS_ROUTE + "/{relationship_id}"): OWN_RESOURCE,
    ("DELETE", RELATIONSHIPS_ROUTE + "/{relationship_id}"): OWN_RESOURCE,
}

# Guarded in the next change of this series; listed so the coverage test holds
# meanwhile. Must be empty once that change lands.
PENDING: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", CONTACT_ROUTE + "/tags"),
        ("DELETE", CONTACT_ROUTE + "/tags/{tag_id}"),
        ("POST", CONTACT_ROUTE + "/favourite"),
    }
)

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@pytest.fixture
async def own_contact(async_connection: AsyncConnection) -> ForeignContact:
    """A contact furnished with every child row, owned by the caller."""
    seeded = await seed_foreign_contact(async_connection)
    await hand_foreign_rows_to_caller(async_connection)
    return seeded


async def _current_etag(client: AsyncClient, seeded: ForeignContact) -> str:
    response = await client.get(f"/api/contacts/{seeded.contact_id}")
    assert response.status_code == 200, response.text[:400]
    return response.headers["ETag"]


async def _send(
    client: AsyncClient,
    spec: CrossUserRequest,
    seeded: ForeignContact,
    if_match: str,
) -> Response:
    return await client.request(
        spec.method,
        spec.path(seeded),
        json=spec.filled_body(seeded),
        headers={"If-Match": if_match},
    )


@pytest.mark.integration
class TestContactRowWritesHonourIfMatch:
    """Each guarded route, under each kind of precondition."""

    @pytest.mark.parametrize(
        "spec", GUARDED_REQUESTS, ids=lambda spec: f"{spec.method} {spec.route}"
    )
    async def test_matching_tag_writes_and_answers_with_the_new_tag(
        self,
        spec: CrossUserRequest,
        integration_api_client: AsyncClient,
        own_contact: ForeignContact,
    ) -> None:
        etag = await _current_etag(integration_api_client, own_contact)

        response = await _send(integration_api_client, spec, own_contact, etag)

        assert response.is_success, response.text[:400]
        assert response.headers.get("ETag") == await _current_etag(
            integration_api_client, own_contact
        )
        # The seeded rows predate the request, so the write moved the version.
        assert response.headers["ETag"] != etag

    @pytest.mark.parametrize(
        "spec", GUARDED_REQUESTS, ids=lambda spec: f"{spec.method} {spec.route}"
    )
    async def test_stale_tag_is_refused_and_writes_nothing(
        self,
        spec: CrossUserRequest,
        integration_api_client: AsyncClient,
        async_connection: AsyncConnection,
        own_contact: ForeignContact,
    ) -> None:
        current = await _current_etag(integration_api_client, own_contact)
        before = await snapshot(async_connection)

        response = await _send(integration_api_client, spec, own_contact, STALE_ETAG)

        assert response.status_code == 412, response.text[:400]
        error: dict[str, Any] = response.json()["errors"][0]
        assert error["code"] == "PRECONDITION_FAILED"
        assert error["meta"]["current_etag"] == current
        assert await snapshot(async_connection) == before

    @pytest.mark.parametrize(
        "spec", GUARDED_REQUESTS, ids=lambda spec: f"{spec.method} {spec.route}"
    )
    async def test_wildcard_writes(
        self,
        spec: CrossUserRequest,
        integration_api_client: AsyncClient,
        own_contact: ForeignContact,
    ) -> None:
        response = await _send(integration_api_client, spec, own_contact, "*")

        assert response.is_success, response.text[:400]


def _mounted_contact_writes(app: Any) -> set[tuple[str, str]]:
    """Every write ``(method, path)`` under ``/api/contacts/{contact_id}``."""
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith(CONTACT_ROUTE)
        for method in operations
        if method.upper() in WRITE_METHODS
    }


@pytest.mark.integration
class TestPreconditionCoverageIsComplete:
    """The table is checked against the app, not against memory."""

    def test_every_contact_write_is_guarded_or_exempted(
        self, test_settings: Any
    ) -> None:
        mounted = _mounted_contact_writes(create_app(settings=test_settings))
        unaccounted = mounted - GUARDED - set(UNGUARDED_BY_DESIGN) - PENDING

        assert not unaccounted, (
            "these contact writes take no If-Match: "
            f"{sorted(unaccounted)}. Guard each (add it to GUARDED), or add it "
            "to UNGUARDED_BY_DESIGN with the reason it does not belong."
        )

    def test_the_table_names_only_served_routes_with_a_request(
        self, test_settings: Any
    ) -> None:
        """A renamed route must not leave a test passing vacuously."""
        mounted = _mounted_contact_writes(create_app(settings=test_settings))
        listed = GUARDED | set(UNGUARDED_BY_DESIGN) | PENDING

        assert not listed - mounted, f"no longer served: {sorted(listed - mounted)}"
        assert {(s.method, s.route) for s in GUARDED_REQUESTS} == GUARDED
