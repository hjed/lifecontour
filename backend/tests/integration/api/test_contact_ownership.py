"""Every contact-by-id endpoint answers 404 for somebody else's contact.

Contacts carry an owner, and every aggregate read is filtered on it in SQL.
That filter only protects a route that goes through it, so this suite asks each
route the question directly: acting as the test user, name another user's
contact and expect what an absent id gets: a 404 that names nothing and
changes nothing.

**404, not 403.** A refusal that distinguishes "not yours" from "does not
exist" confirms the id is real. The body must carry none of the contact's text
either, and every row a write could reach must be byte-identical afterwards, so
a write that happened and *then* returned 404 cannot pass.

**Every request is otherwise valid.** The foreign contact has a method, an
address, a note, an important date, a tag, a relationship, a summary and an
Immich link, and each request names those real ids, so nothing is refused for a
reason other than ownership.

**The table is checked against the app.** ``CROSS_USER_REQUESTS`` is compared
with the app's own route table by
:func:`test_every_contact_id_route_is_covered_by_an_ownership_test`, so a new
route carrying ``{contact_id}`` fails until it is listed here or recorded in
``COVERED_ELSEWHERE`` with the reason it does not belong.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from core_shared.models.contacts.entities import (
    ContactAddress,
    ContactMethod,
    ContactNote,
    ContactRelationship,
    ContactSummary,
    ImportantDate,
    MethodType,
    RelationshipType,
    Tag,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.contacts.value_objects import TagName
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import (
    SqlContactRelationshipRepository,
    SqlContactRepository,
    SqlContactSummaryRepository,
    SqlTagRepository,
)
from app.main import create_app
from tests.integration.contact_seeding import OTHER_USER_ID, TEST_USER_ID, seed_contact

# The foreign contact's private text, every string seeded on it. Each is
# asserted absent from every response body: a 404 that still echoed a name,
# an email or a linked person would leak what it refused.
OTHER_FIRST_NAME = "Theodora"
OTHER_LAST_NAME = "Blackwood-Quince"
OTHER_PARTNER_NAME = "Ignatius"
OTHER_EMAIL = "theodora@foreign.example"
OTHER_STREET = "3 Stone Lane"
OTHER_NOTE = "Keeps the spare key under the third stone."
OTHER_SUMMARY = "Met at the hut; owes me a rope."
IMMICH_PERSON_ID = "person-theirs"
OTHER_TEXT = (
    OTHER_FIRST_NAME,
    OTHER_LAST_NAME,
    OTHER_PARTNER_NAME,
    OTHER_EMAIL,
    OTHER_STREET,
    OTHER_NOTE,
    OTHER_SUMMARY,
    IMMICH_PERSON_ID,
)

# The caller's own contact: the legitimate other half of a merge or a
# relationship. It shares the foreign contact's favourite flag and tag, so
# only the owner filter can tell the two apart in a list.
OWN_FIRST_NAME = "Sarah"

TAG_NAME = "climbing-partners"
UNASSIGNED_TAG_NAME = "unassigned"
IMMICH_SERVER = "http://immich.test"

# Everything a refused request must leave identical. Whole tables rather than
# the foreign contact's rows alone: a refused merge or relationship must not
# touch the caller's own contact either. The outbox and edit-event tables
# catch a deferred write: this client runs no event consumers, so a refused
# request that enqueued a history, summary or search update would otherwise
# leave every other table unchanged. Written out as whole statements so
# nothing here builds SQL by string formatting.
UNCHANGED_ROWS = {
    "contacts": text("SELECT to_jsonb(t) FROM contacts t"),
    "methods": text("SELECT to_jsonb(t) FROM contact_methods t"),
    "addresses": text("SELECT to_jsonb(t) FROM contact_addresses t"),
    "notes": text("SELECT to_jsonb(t) FROM contact_notes t"),
    "important_dates": text("SELECT to_jsonb(t) FROM contact_important_dates t"),
    "tag_assignments": text("SELECT to_jsonb(t) FROM contact_tags t"),
    "tags": text("SELECT to_jsonb(t) FROM tags t"),
    "relationships": text("SELECT to_jsonb(t) FROM contact_relationships t"),
    "summaries": text("SELECT to_jsonb(t) FROM contact_summaries t"),
    "history": text("SELECT to_jsonb(t) FROM field_history t"),
    "links": text("SELECT to_jsonb(t) FROM sync_metadata t"),
    "outbox": text("SELECT to_jsonb(t) FROM outbox_events t"),
    "edit_events": text("SELECT to_jsonb(t) FROM contact_edit_event t"),
}

CONTACT_ROUTE = "/api/contacts/{contact_id}"
METHOD_ROUTE = "/api/contacts/{contact_id}/methods/{method_id}"
ADDRESS_ROUTE = "/api/contacts/{contact_id}/addresses/{address_id}"
IMPORTANT_DATE_ROUTE = "/api/contacts/{contact_id}/important-dates/{date_id}"
RELATIONSHIPS_ROUTE = "/api/contacts/{contact_id}/relationships"
RELATIONSHIP_ROUTE = RELATIONSHIPS_ROUTE + "/{relationship_id}"


# Every refused write is otherwise valid, and every other contact it names is
# the caller's own: then only the ownership check on the URL's contact can
# refuse it. A payload that failed validation, or a second foreign id, would
# answer 404 or 422 even with that check gone.
def _field_update(
    resource_type: str, value: str = "Rewritten By A Stranger"
) -> dict[str, Any]:
    return {
        "data": {
            "type": resource_type,
            "attributes": {"value": value},
        }
    }


_IMPORTANT_DATE_ATTRIBUTES = {
    "date_type": "birthday",
    "precision": "full",
    "year": 1990,
    "month": 1,
    "day": 2,
}

_RELATIONSHIP_ATTRIBUTES = {
    "relationship_type": "sibling",
    "from_contact_id": "{contact_id}",
    "to_contact_id": "{own_contact_id}",
}


@dataclass(frozen=True)
class ForeignContact:
    """Another user's contact, with every child row a real one carries.

    The ids travel together because each request needs a different one, and all
    of them name rows that genuinely exist — otherwise the endpoint would have
    refused the request on its own account.
    """

    contact_id: int
    partner_id: int
    method_id: int
    address_id: int
    note_id: int
    date_id: int
    tag_id: int
    unassigned_tag_id: int
    relationship_id: int
    own_contact_id: int

    def placeholders(self) -> dict[str, str]:
        return {
            "contact_id": str(self.contact_id),
            "partner_id": str(self.partner_id),
            "method_id": str(self.method_id),
            "address_id": str(self.address_id),
            "note_id": str(self.note_id),
            "date_id": str(self.date_id),
            "tag_id": str(self.tag_id),
            "unassigned_tag_id": str(self.unassigned_tag_id),
            "relationship_id": str(self.relationship_id),
            "own_contact_id": str(self.own_contact_id),
        }


@dataclass(frozen=True)
class CrossUserRequest:
    """One request made against another user's contact.

    ``route`` is the mounted path template verbatim, so the coverage test can
    compare this table with the app's routes. Placeholders in the route and the
    body are filled from :meth:`ForeignContact.placeholders`; ``params`` names
    the path parameters that are not ids (a field name).
    """

    method: str
    route: str
    params: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] | None = None

    def path(self, seeded: ForeignContact) -> str:
        return _fill(self.route, {**seeded.placeholders(), **self.params})

    def filled_body(self, seeded: ForeignContact) -> dict[str, Any] | None:
        if self.body is None:
            return None
        filled: dict[str, Any] = json.loads(
            _fill(json.dumps(self.body), seeded.placeholders()),
            object_hook=_ids_as_ints,
        )
        return filled


def _fill(template: str, values: dict[str, str]) -> str:
    for name, value in values.items():
        template = template.replace("{" + name + "}", value)
    return template


# Request schemas type these as integers; JSON:API resource ids stay strings.
_INTEGER_ATTRIBUTES = {"from_contact_id", "to_contact_id", "source_contact_id"}


def _ids_as_ints(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        key: int(value) if key in _INTEGER_ATTRIBUTES else value
        for key, value in obj.items()
    }


CROSS_USER_REQUESTS: tuple[CrossUserRequest, ...] = (
    CrossUserRequest("GET", CONTACT_ROUTE),
    CrossUserRequest(
        "PUT",
        CONTACT_ROUTE,
        body={
            "data": {
                "type": "contacts",
                "id": "{contact_id}",
                "attributes": {"first_name": "Rewritten By A Stranger"},
            }
        },
    ),
    CrossUserRequest("DELETE", CONTACT_ROUTE),
    CrossUserRequest(
        "PATCH",
        "/api/contacts/{contact_id}/fields/{field_name}",
        params={"field_name": "first_name"},
        body=_field_update("contact_fields"),
    ),
    CrossUserRequest("POST", "/api/contacts/{contact_id}/favourite"),
    CrossUserRequest(
        "POST",
        "/api/contacts/{contact_id}/merge",
        body={
            "data": {
                "type": "contact-merge",
                "attributes": {"source_contact_id": "{own_contact_id}"},
            }
        },
    ),
    CrossUserRequest("GET", "/api/contacts/{contact_id}/history"),
    CrossUserRequest("GET", "/api/contacts/{contact_id}/external-links"),
    # Carries weight only because the foreign contact has a real Immich link
    # and the credentials and server are stubbed: otherwise the 404 would
    # arrive with no ownership check at all.
    CrossUserRequest("GET", "/api/contacts/{contact_id}/avatar"),
    CrossUserRequest("GET", "/api/contacts/{contact_id}/journals"),
    CrossUserRequest(
        "PATCH",
        "/api/contacts/{contact_id}/summary",
        body={"data": {"is_disabled": True}},
    ),
    CrossUserRequest("POST", "/api/contacts/{contact_id}/summary/refresh"),
    CrossUserRequest(
        "POST",
        "/api/contacts/{contact_id}/methods",
        body={
            "data": {
                "type": "contact_methods",
                "attributes": {"method_type": "email", "value": "x@stranger.example"},
            }
        },
    ),
    CrossUserRequest("DELETE", METHOD_ROUTE),
    CrossUserRequest(
        "PATCH",
        METHOD_ROUTE + "/fields/{field_name}",
        params={"field_name": "value"},
        body=_field_update("contact_method_fields", "stranger@stranger.example"),
    ),
    CrossUserRequest(
        "POST",
        "/api/contacts/{contact_id}/addresses",
        body={
            "data": {
                "type": "contact_addresses",
                "attributes": {"street_line_1": "1 Stranger St", "country_code": "AU"},
            }
        },
    ),
    CrossUserRequest("DELETE", ADDRESS_ROUTE),
    CrossUserRequest(
        "PATCH",
        ADDRESS_ROUTE + "/fields/{field_name}",
        params={"field_name": "street_line_1"},
        body=_field_update("contact_address_fields"),
    ),
    CrossUserRequest(
        "PATCH",
        "/api/contacts/{contact_id}/notes/{note_id}/fields/{field_name}",
        params={"field_name": "content"},
        body=_field_update("contact_note_fields"),
    ),
    CrossUserRequest(
        "POST",
        "/api/contacts/{contact_id}/important-dates",
        body={
            "data": {
                "type": "contact_important_dates",
                "attributes": _IMPORTANT_DATE_ATTRIBUTES,
            }
        },
    ),
    CrossUserRequest(
        "PUT",
        IMPORTANT_DATE_ROUTE,
        body={
            "data": {
                "type": "contact_important_dates",
                "id": "{date_id}",
                "attributes": _IMPORTANT_DATE_ATTRIBUTES,
            }
        },
    ),
    CrossUserRequest("DELETE", IMPORTANT_DATE_ROUTE),
    CrossUserRequest("GET", "/api/contacts/{contact_id}/tags"),
    CrossUserRequest(
        "POST",
        "/api/contacts/{contact_id}/tags",
        body={"data": {"type": "tags", "id": "{unassigned_tag_id}"}},
    ),
    CrossUserRequest("DELETE", "/api/contacts/{contact_id}/tags/{tag_id}"),
    CrossUserRequest("GET", RELATIONSHIPS_ROUTE),
    CrossUserRequest(
        "POST",
        RELATIONSHIPS_ROUTE,
        body={
            "data": {
                "type": "contact_relationships",
                "attributes": {
                    **_RELATIONSHIP_ATTRIBUTES,
                    "relationship_type": "friend",
                },
            }
        },
    ),
    CrossUserRequest("GET", RELATIONSHIP_ROUTE),
    CrossUserRequest(
        "PUT",
        RELATIONSHIP_ROUTE,
        body={
            "data": {
                "type": "contact_relationships",
                "id": "{relationship_id}",
                "attributes": _RELATIONSHIP_ATTRIBUTES,
            }
        },
    ),
    CrossUserRequest("DELETE", RELATIONSHIP_ROUTE),
)

# Operations deliberately not in the table above, each with the reason. Keyed
# on ``(method, path)`` so an exemption cannot quietly cover a verb the path
# grows later.
JOURNAL_CONTACT_ROUTE = (
    "/api/journals/{journal_id}/relationships/contacts/{contact_id}/{relationship_type}"
)
BY_JOURNAL_SUITE = (
    "keyed on the journal, which is owner-checked first; asserted by "
    "test_journal_ownership.py"
)

COVERED_ELSEWHERE: dict[tuple[str, str], str] = {
    ("PATCH", JOURNAL_CONTACT_ROUTE): BY_JOURNAL_SUITE,
    ("DELETE", JOURNAL_CONTACT_ROUTE): BY_JOURNAL_SUITE,
    ("DELETE", "/api/tasks/{task_id}/relationships/contacts/{contact_id}"): (
        "keyed on the task, which is owner-checked first; asserted by "
        "test_task_endpoints.py (unlinking another user's task)"
    ),
}


def _mounted_contact_id_routes(app: Any) -> set[tuple[str, str]]:
    """Every ``(method, path)`` the app serves whose path carries a contact id."""
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if "{contact_id}" in path
        for method in operations
        if method.upper() not in {"HEAD", "OPTIONS"}
    }


async def _snapshot(connection: AsyncConnection) -> dict[str, list[str]]:
    """Every row a contact write could reach, as comparable JSON.

    Stricter than counting rows: it catches a rewritten name, a flipped
    favourite and a disabled summary, none of which move a count.
    """
    state: dict[str, list[str]] = {}
    for name, query in UNCHANGED_ROWS.items():
        rows = await connection.execute(query)
        state[name] = sorted(str(row[0]) for row in rows.fetchall())
    return state


def _assert_nothing_leaked(response: httpx.Response) -> None:
    for fragment in OTHER_TEXT:
        assert fragment not in response.text, (
            f"the response names the foreign contact ({fragment!r})"
        )


async def _link_to_immich(connection: AsyncConnection, contact_id: int) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO sync_metadata (
                user_id, internal_id, integration_source, external_id,
                last_synced_at, version_hash, sync_status, retry_count,
                internal_entity_type, external_entity_type, created_at, updated_at
            ) VALUES (
                :uid, :iid, 'immich', :eid, now(), 'h', 'success', 0,
                'contact', 'person', now(), now()
            )
            """
        ),
        {"uid": OTHER_USER_ID, "iid": contact_id, "eid": IMMICH_PERSON_ID},
    )


async def _tag(repo: SqlTagRepository, name: str) -> int:
    tag = await repo.save(Tag(name=TagName(name)))
    assert tag.id is not None
    return tag.id


@pytest.fixture
async def foreign_contact(async_connection: AsyncConnection) -> ForeignContact:
    """Another user's contact, furnished the way a real one would be."""
    repo = SqlContactRepository(async_connection)
    contact_id = await seed_contact(
        async_connection,
        user_id=OTHER_USER_ID,
        first_name=OTHER_FIRST_NAME,
        last_name=OTHER_LAST_NAME,
        is_favourite=True,
    )
    partner_id = await seed_contact(
        async_connection, user_id=OTHER_USER_ID, first_name=OTHER_PARTNER_NAME
    )

    method = await repo.add_method(
        contact_id,
        ContactMethod(
            method_type=MethodType.EMAIL,
            value=OTHER_EMAIL,
            contact_id=contact_id,
            is_primary=True,
        ),
    )
    address = await repo.add_address(
        contact_id,
        ContactAddress(
            street_line_1=OTHER_STREET, country_code="AU", contact_id=contact_id
        ),
    )
    note = await repo.add_note(
        contact_id, ContactNote(content=OTHER_NOTE, contact_id=contact_id)
    )
    important_date = await repo.add_important_date(
        contact_id,
        ImportantDate(
            contact_id=contact_id,
            date_type=ImportantDateType.BIRTHDAY,
            precision=DatePrecision.FULL,
            year=1985,
            month=3,
            day=14,
        ),
    )

    tag_repo = SqlTagRepository(async_connection)
    tag_id = await _tag(tag_repo, TAG_NAME)
    unassigned_tag_id = await _tag(tag_repo, UNASSIGNED_TAG_NAME)
    await repo.assign_tag(contact_id, tag_id)

    relationship = await SqlContactRelationshipRepository(async_connection).create(
        ContactRelationship(
            from_contact_id=contact_id,
            to_contact_id=partner_id,
            relationship_type=RelationshipType.PARTNER,
        )
    )
    await SqlContactSummaryRepository(async_connection).upsert(
        ContactSummary(contact_id=contact_id, summary_text=OTHER_SUMMARY)
    )
    await _link_to_immich(async_connection, contact_id)

    own_contact_id = await seed_contact(
        async_connection, first_name=OWN_FIRST_NAME, is_favourite=True
    )
    await repo.assign_tag(own_contact_id, tag_id)

    assert method.id is not None
    assert address.id is not None
    assert note.id is not None
    assert important_date.id is not None
    assert relationship.id is not None
    return ForeignContact(
        contact_id=contact_id,
        partner_id=partner_id,
        method_id=method.id,
        address_id=address.id,
        note_id=note.id,
        date_id=important_date.id,
        tag_id=tag_id,
        unassigned_tag_id=unassigned_tag_id,
        relationship_id=relationship.id,
        own_contact_id=own_contact_id,
    )


@pytest.fixture
def immich_serves_every_thumbnail() -> Iterator[None]:
    """Credentials and an Immich server that would answer any avatar request.

    With these in place the avatar route can only refuse a foreign contact by
    checking its owner; without them it would 404 for want of an Immich
    account, whoever owned the contact.
    """
    with (
        patch(
            "app.infrastructure.auth.immich_token_service.ImmichTokenService.get_credentials",
            new=AsyncMock(return_value=(IMMICH_SERVER, "the-callers-key")),
        ),
        respx.mock(assert_all_called=False) as immich,
    ):
        immich.get(f"{IMMICH_SERVER}/api/people/{IMMICH_PERSON_ID}/thumbnail").mock(
            return_value=httpx.Response(
                200, content=b"\x89PNG", headers={"content-type": "image/png"}
            )
        )
        yield


@pytest.mark.integration
@pytest.mark.usefixtures("immich_serves_every_thumbnail")
class TestContactOwnershipIsEnforced:
    """No contact-by-id endpoint acts on a contact the caller does not own."""

    @pytest.mark.parametrize(
        "request_spec",
        CROSS_USER_REQUESTS,
        ids=lambda spec: f"{spec.method} {spec.route}",
    )
    async def test_another_users_contact_reads_as_an_absent_one(
        self,
        request_spec: CrossUserRequest,
        integration_api_client: AsyncClient,
        async_connection: AsyncConnection,
        foreign_contact: ForeignContact,
    ) -> None:
        """The endpoint answers 404, names nothing, and changes nothing."""
        before = await _snapshot(async_connection)

        response = await integration_api_client.request(
            request_spec.method,
            request_spec.path(foreign_contact),
            json=request_spec.filled_body(foreign_contact),
        )

        assert response.status_code == 404, (
            f"{request_spec.method} {request_spec.route} answered "
            f"{response.status_code} for another user's contact: {response.text[:400]}"
        )
        _assert_nothing_leaked(response)
        assert await _snapshot(async_connection) == before

    async def test_merging_another_users_contact_into_your_own_is_refused(
        self,
        integration_api_client: AsyncClient,
        async_connection: AsyncConnection,
        foreign_contact: ForeignContact,
    ) -> None:
        """The merge *source* is owner-checked too, not only the survivor.

        A successful merge would copy their methods, notes and dates into a
        contact the caller can simply open, then delete theirs.
        """
        before = await _snapshot(async_connection)

        response = await integration_api_client.post(
            f"/api/contacts/{foreign_contact.own_contact_id}/merge",
            json={
                "data": {
                    "type": "contact-merge",
                    "attributes": {"source_contact_id": foreign_contact.contact_id},
                }
            },
        )

        assert response.status_code == 404, response.text[:400]
        _assert_nothing_leaked(response)
        assert await _snapshot(async_connection) == before

    async def test_relating_your_contact_to_theirs_is_refused(
        self,
        integration_api_client: AsyncClient,
        async_connection: AsyncConnection,
        foreign_contact: ForeignContact,
    ) -> None:
        """Both ends of a relationship must be the caller's."""
        before = await _snapshot(async_connection)
        own_id = foreign_contact.own_contact_id

        response = await integration_api_client.post(
            f"/api/contacts/{own_id}/relationships",
            json={
                "data": {
                    "type": "contact_relationships",
                    "attributes": {
                        "relationship_type": "friend",
                        "from_contact_id": own_id,
                        "to_contact_id": foreign_contact.contact_id,
                    },
                }
            },
        )

        assert response.status_code == 404, response.text[:400]
        _assert_nothing_leaked(response)
        assert await _snapshot(async_connection) == before

    async def test_your_own_avatar_is_served(
        self,
        integration_api_client: AsyncClient,
        async_connection: AsyncConnection,
        foreign_contact: ForeignContact,
    ) -> None:
        """The stubbed Immich would serve an avatar, so the 404 above is real.

        The same person linked to the caller's own contact comes back, which
        is what makes the foreign contact's 404 an ownership refusal.
        """
        await async_connection.execute(
            text(
                """
                UPDATE sync_metadata SET user_id = :uid, internal_id = :iid
                WHERE external_id = :eid
                """
            ),
            {
                "uid": TEST_USER_ID,
                "iid": foreign_contact.own_contact_id,
                "eid": IMMICH_PERSON_ID,
            },
        )

        response = await integration_api_client.get(
            f"/api/contacts/{foreign_contact.own_contact_id}/avatar"
        )

        assert response.status_code == 200, response.text[:400]
        assert response.content == b"\x89PNG"


async def _listed_first_names(client: AsyncClient, **params: Any) -> list[str]:
    response = await client.get("/api/contacts", params=params)
    assert response.status_code == 200, response.text[:400]
    body = response.json()
    assert body["meta"]["total_count"] == len(body["data"])
    return [contact["attributes"]["first_name"] for contact in body["data"]]


@pytest.mark.integration
class TestContactListsHoldOnlyYourContacts:
    """Their contact matches every filter as well as yours; only yours is listed.

    The foreign contact is a favourite and carries the same tag as the
    caller's, so the owner filter is the only thing that separates them. The
    count is asserted with each list because it is a separate query.
    """

    @pytest.mark.usefixtures("foreign_contact")
    async def test_the_list_holds_only_your_contacts(
        self, integration_api_client: AsyncClient
    ) -> None:
        assert await _listed_first_names(integration_api_client) == [OWN_FIRST_NAME]

    @pytest.mark.usefixtures("foreign_contact")
    async def test_the_favourites_filter_holds_only_your_contacts(
        self, integration_api_client: AsyncClient
    ) -> None:
        assert await _listed_first_names(integration_api_client, favourite=True) == [
            OWN_FIRST_NAME
        ]

    async def test_the_tag_filter_holds_only_your_contacts(
        self, integration_api_client: AsyncClient, foreign_contact: ForeignContact
    ) -> None:
        assert await _listed_first_names(
            integration_api_client, tag_ids=foreign_contact.tag_id
        ) == [OWN_FIRST_NAME]

    async def test_cleanup_leaves_another_users_contacts(
        self,
        integration_api_client: AsyncClient,
        async_connection: AsyncConnection,
        foreign_contact: ForeignContact,
    ) -> None:
        """The test-only bulk delete removes the caller's contacts, not theirs."""
        response = await integration_api_client.delete("/api/contacts/test/cleanup")

        assert response.status_code == 204, response.text[:400]
        remaining = await async_connection.execute(
            text("SELECT id FROM contacts ORDER BY id")
        )
        assert [row.id for row in remaining] == [
            foreign_contact.contact_id,
            foreign_contact.partner_id,
        ]


@pytest.mark.integration
class TestOwnershipCoverageIsComplete:
    """The route table is checked against the app, not against memory."""

    def test_every_contact_id_route_is_covered_by_an_ownership_test(
        self, test_settings: Any
    ) -> None:
        """Every mounted ``{contact_id}`` route is accounted for.

        Adding a contact-by-id route fails this test until it is listed in
        ``CROSS_USER_REQUESTS`` or in ``COVERED_ELSEWHERE`` with its reason.
        """
        mounted = _mounted_contact_id_routes(create_app(settings=test_settings))
        tested = {(spec.method, spec.route) for spec in CROSS_USER_REQUESTS}
        uncovered = mounted - tested - set(COVERED_ELSEWHERE)

        assert not uncovered, (
            "these contact-by-id operations have no ownership test: "
            f"{sorted(uncovered)}. Add each to CROSS_USER_REQUESTS, or to "
            "COVERED_ELSEWHERE with the reason it does not belong there."
        )

    def test_the_table_does_not_name_routes_the_app_does_not_serve(
        self, test_settings: Any
    ) -> None:
        """A renamed or deleted route must not leave a test passing vacuously."""
        mounted = _mounted_contact_id_routes(create_app(settings=test_settings))

        stale_requests = {
            (spec.method, spec.route)
            for spec in CROSS_USER_REQUESTS
            if (spec.method, spec.route) not in mounted
        }
        stale_exemptions = set(COVERED_ELSEWHERE) - mounted

        assert not stale_requests, f"no longer served: {sorted(stale_requests)}"
        assert not stale_exemptions, f"no longer served: {sorted(stale_exemptions)}"
