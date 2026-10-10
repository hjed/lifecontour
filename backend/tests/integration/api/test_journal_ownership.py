"""Every journal-by-id endpoint answers 404 for somebody else's journal.

Issue #1267: the endpoints authenticated but never compared the journal's
``user_id`` with the session user, so any authenticated caller could read a
journal by id — and, worse, rewrite its title and content, add and remove its
types, and attach or detach its contacts and tags.

**404, not 403.** A refusal that distinguishes "not yours" from "does not exist"
is itself a disclosure: it confirms the id is real. Every surface here answers
exactly as it does for an id that never existed, which is the stance MCP's read
and the task domain's ports already take.

**Every request is otherwise valid.** The journal seeded here has a mood row, a
contact relationship and a tag assignment, and each request names those real
ids, so nothing is refused for a reason other than ownership. A test whose
request would have failed validation anyway proves nothing about the check it
claims to exercise.

**The table is the point.** A check each controller must remember to write is
what produced the bug, so ``CROSS_USER_REQUESTS`` below is checked against the
app's own route table by
:func:`test_every_journal_id_route_is_covered_by_an_ownership_test`. A new route
carrying ``{journal_id}`` fails that test until it is either listed here or
recorded in ``COVERED_ELSEWHERE`` against the reason it does not belong — so the
next endpoint cannot quietly ship without an ownership test.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

import pytest
from core_shared.models.journals import (
    JournalContactRelationship,
    JournalContactRelationshipType,
)
from core_shared.models.journals.attendee_status import AttendeeStatus
from core_shared.models.journals.mood_data import MoodData
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.journal_tag_repository import SqlJournalTagRepository
from app.core.journal.adapters.sql.mood_data_repository import SqlMoodDataRepository
from app.core.journal.models.journal_tag import JournalTag
from app.main import create_app
from tests.integration.contact_seeding import TEST_USER_ID
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    create_contact,
    create_journal,
)

# The journal these tests probe for. Both fields are asserted absent from every
# response body: a 404 that still echoed the title would leak what it refused.
OTHER_TITLE = "Somebody Else's Expedition"
OTHER_CONTENT = "The hut is booked under my name."
# Their tag names, likewise asserted absent: a tag's name is its content.
OTHER_TAG = "their-assigned-tag"
OTHER_UNASSIGNED_TAG = "their-other-tag"
# Their contact's name, asserted absent: a refused link must not name the person.
OTHER_CONTACT = "TheirFriend"
# The caller's own tag, the legitimate other half of a cross-owner merge.
OWN_TAG = "my-own-tag"

# Everything a refused request must leave identical: the journal row, and every
# association a write could have reached. Written out as whole statements rather
# than interpolating a table name, so nothing here builds SQL by string
# formatting — even in a test, and even from a constant.
UNCHANGED_ROWS = {
    "journals": text("SELECT to_jsonb(t) FROM journals t WHERE id = :id"),
    "mood": text("SELECT to_jsonb(t) FROM journal_mood_data t WHERE journal_id = :id"),
    "plan": text("SELECT to_jsonb(t) FROM journal_plan_data t WHERE journal_id = :id"),
    "contacts": text(
        "SELECT to_jsonb(t) FROM journal_contact_relationships t WHERE journal_id = :id"
    ),
    "tags": text(
        "SELECT to_jsonb(t) FROM journal_tag_assignments t WHERE journal_id = :id"
    ),
    # Every tag the journal's owner holds: a refused tag write must leave their
    # whole namespace — names, colours, hierarchy — as it was.
    "tag_namespace": text(
        "SELECT to_jsonb(t) FROM journal_tags t "
        "WHERE user_id = (SELECT user_id FROM journals WHERE id = :id)"
    ),
}

# Values shared by several table entries, named so the table reads as one shape
# rather than repeating the same string in unrelated-looking places.
MOOD_TYPE = "MOOD_RATING"
PARTICIPANT = "PARTICIPANT"
JOURNAL_ROUTE = "/api/journals/{journal_id}"
CONTACT_RELATIONSHIP_RESOURCE = "journal-contact-relationships"
CONTACT_RELATIONSHIP_ROUTE = (
    "/api/journals/{journal_id}/relationships/contacts/{contact_id}/{relationship_type}"
)

_JOURNAL_BODY = {
    "data": {
        "type": "journals",
        "id": "{journal_id}",
        "attributes": {
            "title": "Rewritten By A Stranger",
            "content": "Rewritten by a stranger.",
            "event_date_range": {
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-01T23:59:59Z",
            },
        },
    }
}


@dataclass(frozen=True)
class ForeignJournal:
    """Another user's journal, with the associations a real one carries.

    The ids travel together because each request needs a different one, and all
    of them have to name rows that genuinely exist — otherwise the endpoint
    would have refused the request on its own account.
    """

    journal_id: int
    contact_id: int
    assigned_tag_id: str
    unassigned_tag_id: str
    attacker_journal_id: int
    attacker_tag_id: str

    def placeholders(self) -> dict[str, str]:
        return {
            "journal_id": str(self.journal_id),
            "contact_id": str(self.contact_id),
            "tag_id": self.assigned_tag_id,
            "unassigned_tag_id": self.unassigned_tag_id,
            "source_journal_id": str(self.attacker_journal_id),
            "own_tag_id": self.attacker_tag_id,
        }


@dataclass(frozen=True)
class CrossUserRequest:
    """One request made against another user's journal.

    ``route`` is the mounted path template verbatim, so the coverage test below
    can compare this table against the app's own routes without re-deriving
    anything. Placeholders in both the route and the body are filled from
    :meth:`ForeignJournal.placeholders`.
    """

    method: str
    route: str
    params: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] | None = None

    def path(self, seeded: ForeignJournal) -> str:
        return _fill(self.route, {**seeded.placeholders(), **self.params})

    def filled_body(self, seeded: ForeignJournal) -> dict[str, Any] | None:
        if self.body is None:
            return None
        filled: dict[str, Any] = json.loads(
            _fill(json.dumps(self.body), seeded.placeholders())
        )
        return filled


def _fill(template: str, values: dict[str, str]) -> str:
    for name, value in values.items():
        template = template.replace("{" + name + "}", value)
    return template


CROSS_USER_REQUESTS: tuple[CrossUserRequest, ...] = (
    CrossUserRequest("GET", JOURNAL_ROUTE),
    CrossUserRequest("PUT", JOURNAL_ROUTE, body=_JOURNAL_BODY),
    CrossUserRequest("PATCH", JOURNAL_ROUTE, body=_JOURNAL_BODY),
    CrossUserRequest("DELETE", JOURNAL_ROUTE),
    CrossUserRequest(
        "POST",
        "/api/journals/{journal_id}/types",
        body={
            "data": {
                "type": "journal-types",
                "attributes": {"journal_type": "PLAN"},
            }
        },
    ),
    CrossUserRequest(
        "DELETE",
        "/api/journals/{journal_id}/types/{journal_type}",
        params={"journal_type": MOOD_TYPE},
    ),
    CrossUserRequest(
        "PUT",
        "/api/journals/{journal_id}/types/{journal_type}/data",
        params={"journal_type": MOOD_TYPE},
        body={
            "data": {
                "type": "journal-type-data",
                "attributes": {"mood_value": 1, "mood_label": "Rewritten"},
            }
        },
    ),
    CrossUserRequest(
        "POST",
        "/api/journals/{journal_id}/relationships/contacts",
        body={
            "data": {
                "type": CONTACT_RELATIONSHIP_RESOURCE,
                "attributes": {
                    "contact_id": "{contact_id}",
                    "relationship_type": "MENTION",
                },
            }
        },
    ),
    CrossUserRequest(
        "PATCH",
        CONTACT_RELATIONSHIP_ROUTE,
        params={"relationship_type": PARTICIPANT},
        body={
            "data": {
                "type": CONTACT_RELATIONSHIP_RESOURCE,
                "attributes": {"status": "ATTENDING"},
            }
        },
    ),
    CrossUserRequest(
        "DELETE",
        CONTACT_RELATIONSHIP_ROUTE,
        params={"relationship_type": PARTICIPANT},
    ),
    CrossUserRequest(
        "POST",
        "/api/journals/{journal_id}/relationships/tags",
        body={
            "data": {
                "type": "journal-tag-assignment",
                "attributes": {"tag_id": "{unassigned_tag_id}"},
            }
        },
    ),
    CrossUserRequest(
        "DELETE",
        "/api/journals/{journal_id}/relationships/tags/{tag_id}",
    ),
    CrossUserRequest(
        "POST",
        "/api/journals/{journal_id}/merge",
        body={
            "data": {
                "type": "journal-merge",
                "attributes": {"source_journal_id": "{source_journal_id}"},
            }
        },
    ),
    CrossUserRequest("GET", "/api/journals/{journal_id}/history"),
    CrossUserRequest("GET", "/api/journals/{journal_id}/external-links"),
    # This one cannot carry its own weight here, and saying so is the point: the
    # seeded journal has no Immich album, so the 404 would arrive even with no
    # ownership check at all. The refusal is proved in test_album_cover_route.py
    # (`test_album_cover_of_another_users_album_is_never_fetched`), which seeds a
    # real album and stubs the credentials so an unscoped lookup would visibly
    # succeed. The entry stays because the endpoint must still answer 404.
    CrossUserRequest("GET", "/api/journals/{journal_id}/album-cover"),
    CrossUserRequest(
        "POST", "/api/journals/incomplete-outdoor-activities/{journal_id}/dismiss"
    ),
    CrossUserRequest(
        "POST", "/api/journals/incomplete-outdoor-activities/{journal_id}/undismiss"
    ),
)

# Operations deliberately not in the table above, each with the reason. These
# are claims that can be checked by reading what they name — the point of
# writing them down rather than silently omitting the route.
#
# Keyed on ``(method, path)`` rather than path alone: a path-keyed exemption
# would cover every verb the path ever grows, so adding an unguarded write to an
# already-exempted path would slip past this guard — the exact class of omission
# the guard exists to catch.
ROUTES_COLLECTION = "/api/journals/{journal_id}/routes"
ROUTES_MEMBER = "/api/journals/{journal_id}/routes/{route_id}"
JOURNAL_TASKS = "/api/journals/{journal_id}/tasks"

BY_ROUTE_SUITE = (
    "asserted by test_route_endpoints.py; those handlers already refuse a "
    "journal that is not the caller's"
)
BY_SERIES_SUITE = (
    "the series is resolved and owner-checked before the journal is reached; "
    "asserted in test_journal_series_endpoints.py"
)

COVERED_ELSEWHERE: dict[tuple[str, str], str] = {
    ("GET", ROUTES_COLLECTION): BY_ROUTE_SUITE,
    ("POST", ROUTES_COLLECTION): BY_ROUTE_SUITE,
    ("GET", ROUTES_MEMBER): BY_ROUTE_SUITE,
    ("PUT", ROUTES_MEMBER): BY_ROUTE_SUITE,
    ("DELETE", ROUTES_MEMBER): BY_ROUTE_SUITE,
    ("GET", JOURNAL_TASKS): (
        "asserted by test_task_endpoints.py — the task domain's reads are "
        "owner-scoped in SQL"
    ),
    ("POST", JOURNAL_TASKS): (
        "asserted by test_task_endpoints.py — creating against another user's "
        "journal is refused as an absent anchor"
    ),
    (
        "DELETE",
        "/api/tasks/{task_id}/relationships/intermediate-journals/{journal_id}",
    ): ("keyed on the task, not the journal; asserted by test_task_endpoints.py"),
    ("POST", "/api/journals/{journal_id}/relationships/series"): BY_SERIES_SUITE,
    ("DELETE", "/api/journals/{journal_id}/relationships/series/{series_id}"): (
        BY_SERIES_SUITE
    ),
    ("GET", "/api/integrations/strava/journals/{journal_id}/unmatched-athletes"): (
        "the query is owner-scoped (get_by_journal_id(user.id, …)), so another "
        "user's journal yields an empty list rather than a 404 — nothing to leak"
    ),
}


def _mounted_journal_id_routes(app: Any) -> set[tuple[str, str]]:
    """Every ``(method, path)`` the app serves whose path carries a journal id.

    Read from the app's own OpenAPI paths rather than from a list kept by hand,
    which is the only version of this that stays true as endpoints are added.
    """
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if "{journal_id}" in path
        for method in operations
        if method.upper() not in {"HEAD", "OPTIONS"}
    }


async def _snapshot(connection: AsyncConnection, journal_id: int) -> dict[str, Any]:
    """The journal row and every association row, as comparable JSON.

    Comparing this before and after is stricter than counting rows: it catches a
    rewritten title, a flipped RSVP status and a changed mood value, none of
    which move a count.
    """
    state: dict[str, Any] = {}
    for name, query in UNCHANGED_ROWS.items():
        rows = await connection.execute(query, {"id": journal_id})
        state[name] = sorted(str(row[0]) for row in rows.fetchall())
    return state


@pytest.fixture
async def foreign_journal(async_connection: AsyncConnection) -> ForeignJournal:
    """Another user's journal, furnished the way a real one would be."""
    journal_repo = SqlJournalRepository(async_connection)
    journal_id = await create_journal(
        journal_repo, title=OTHER_TITLE, user_id=OTHER_USER_ID
    )
    await async_connection.execute(
        text("UPDATE journals SET content = :content WHERE id = :id"),
        {"content": OTHER_CONTENT, "id": journal_id},
    )

    await SqlMoodDataRepository(async_connection).save(
        MoodData(journal_id=journal_id, mood_value=9, mood_label="Elated")
    )

    contact_id = await create_contact(
        async_connection, first_name=OTHER_CONTACT, user_id=OTHER_USER_ID
    )
    await SqlJournalContactRelationshipRepository(async_connection).create(
        JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
            status=AttendeeStatus.NO_REPLY,
        )
    )

    tag_repo = SqlJournalTagRepository(async_connection)
    assigned = await tag_repo.save(JournalTag(user_id=OTHER_USER_ID, name=OTHER_TAG))
    unassigned = await tag_repo.save(
        JournalTag(user_id=OTHER_USER_ID, name=OTHER_UNASSIGNED_TAG)
    )
    assert assigned.id is not None
    assert unassigned.id is not None
    await tag_repo.assign_tag(journal_id, assigned.id, user_id=OTHER_USER_ID)
    own_tag = await tag_repo.save(JournalTag(user_id=TEST_USER_ID, name=OWN_TAG))
    assert own_tag.id is not None

    return ForeignJournal(
        journal_id=journal_id,
        contact_id=contact_id,
        assigned_tag_id=str(assigned.id),
        unassigned_tag_id=str(unassigned.id),
        attacker_journal_id=await create_journal(journal_repo, title="My Own Journal"),
        attacker_tag_id=str(own_tag.id),
    )


@pytest.mark.integration
class TestJournalOwnershipIsEnforced:
    """No journal-by-id endpoint acts on a journal the caller does not own."""

    @pytest.mark.parametrize(
        "request_spec",
        CROSS_USER_REQUESTS,
        ids=lambda spec: f"{spec.method} {spec.route}",
    )
    async def test_another_users_journal_reads_as_an_absent_one(
        self,
        request_spec: CrossUserRequest,
        integration_api_client,
        async_connection: AsyncConnection,
        foreign_journal: ForeignJournal,
    ) -> None:
        """The endpoint answers 404 and leaves the journal exactly as it was.

        Three things are asserted together because any one alone would pass for
        the wrong reason: the status hides whether the id exists, the body
        carries none of the journal's text, and every row is byte-identical
        afterwards — so a write that happened and *then* returned 404 cannot
        pass either.
        """
        before = await _snapshot(async_connection, foreign_journal.journal_id)

        response = await integration_api_client.request(
            request_spec.method,
            request_spec.path(foreign_journal),
            json=request_spec.filled_body(foreign_journal),
        )

        assert response.status_code == 404, (
            f"{request_spec.method} {request_spec.route} answered "
            f"{response.status_code} for another user's journal: {response.text[:400]}"
        )
        assert OTHER_TITLE not in response.text
        assert OTHER_CONTENT not in response.text
        assert await _snapshot(async_connection, foreign_journal.journal_id) == before

    async def test_merging_another_users_journal_into_your_own_is_refused(
        self,
        integration_api_client,
        async_connection: AsyncConnection,
        foreign_journal: ForeignJournal,
    ) -> None:
        """The *source* of a merge is owner-checked too, not just the target.

        Merge is the one write that reads a second journal by id, and it is
        destructive: a successful merge would copy their content into a journal
        the caller can then simply open.
        """
        before = await _snapshot(async_connection, foreign_journal.journal_id)

        response = await integration_api_client.post(
            f"/api/journals/{foreign_journal.attacker_journal_id}/merge",
            json={
                "data": {
                    "type": "journal-merge",
                    "attributes": {
                        "source_journal_id": str(foreign_journal.journal_id)
                    },
                }
            },
        )

        assert response.status_code == 404, response.text[:400]
        assert OTHER_TITLE not in response.text
        assert OTHER_CONTENT not in response.text
        assert await _snapshot(async_connection, foreign_journal.journal_id) == before


@pytest.mark.integration
class TestOwnershipCoverageIsComplete:
    """The route table is checked against the app, not against memory."""

    def test_every_journal_id_route_is_covered_by_an_ownership_test(
        self, test_settings
    ) -> None:
        """Every mounted ``{journal_id}`` route is accounted for.

        This is the half of issue #1267's fix that an owner-scoped repository
        method cannot give on its own: the check still has to be *called*, and
        the endpoint that forgets to call it is the one nobody wrote a test for.
        Adding a journal-by-id route now fails this test until it is listed in
        ``CROSS_USER_REQUESTS`` or in ``COVERED_ELSEWHERE`` with its reason.
        """
        mounted = _mounted_journal_id_routes(create_app(settings=test_settings))
        tested = {(spec.method, spec.route) for spec in CROSS_USER_REQUESTS}
        uncovered = mounted - tested - set(COVERED_ELSEWHERE)

        assert not uncovered, (
            "these journal-by-id operations have no ownership test: "
            f"{sorted(uncovered)}. Add each to CROSS_USER_REQUESTS, or to "
            "COVERED_ELSEWHERE with the reason it does not belong there."
        )

    def test_the_table_does_not_name_routes_the_app_does_not_serve(
        self, test_settings
    ) -> None:
        """A renamed or deleted route must not leave a test passing vacuously.

        Without this, a route dropped from the app would keep its entry here and
        the coverage test above would go on passing while nothing was checked.
        """
        mounted = _mounted_journal_id_routes(create_app(settings=test_settings))

        stale_requests = {
            (spec.method, spec.route)
            for spec in CROSS_USER_REQUESTS
            if (spec.method, spec.route) not in mounted
        }
        stale_exemptions = set(COVERED_ELSEWHERE) - mounted

        assert not stale_requests, f"no longer served: {sorted(stale_requests)}"
        assert not stale_exemptions, f"no longer served: {sorted(stale_exemptions)}"


# --------------------------------------------------------------------------- #
# Journal tags                                                                #
# --------------------------------------------------------------------------- #
#
# Tags are owned too, and their management routes are keyed by the tag rather
# than by a journal, so the guard above never sees them. Each request below
# names the foreign journal's owner's tag; a refusal must answer 404 and leave
# their tag namespace and the journal's assignments exactly as they were.
JOURNAL_TAG_ROUTE = "/api/journals/tags/{tag_id}"

CROSS_USER_TAG_REQUESTS: tuple[CrossUserRequest, ...] = (
    CrossUserRequest(
        "PATCH",
        JOURNAL_TAG_ROUTE,
        body={
            "data": {
                "type": "journal-tags",
                "id": "{tag_id}",
                "attributes": {"name": "Renamed By A Stranger", "color": "#000000"},
            }
        },
    ),
    CrossUserRequest("DELETE", JOURNAL_TAG_ROUTE),
    CrossUserRequest(
        "POST",
        JOURNAL_TAG_ROUTE + "/merge",
        body={
            "data": {
                "type": "journal-tags",
                "attributes": {"target_tag_id": "{own_tag_id}"},
            }
        },
    ),
)


def _mounted_journal_tag_id_routes(app: Any) -> set[tuple[str, str]]:
    """Every ``(method, path)`` under ``/api/journals`` that carries a tag id."""
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/journals/") and "{tag_id}" in path
        for method in operations
        if method.upper() not in {"HEAD", "OPTIONS"}
    }


async def _assignment_exists(
    connection: AsyncConnection, journal_id: int, tag_id: str
) -> bool:
    row = await connection.execute(
        text(
            "SELECT 1 FROM journal_tag_assignments "
            "WHERE journal_id = :journal_id AND tag_id = CAST(:tag_id AS uuid)"
        ),
        {"journal_id": journal_id, "tag_id": tag_id},
    )
    return row.fetchone() is not None


async def _tag_exists(connection: AsyncConnection, tag_id: str) -> bool:
    row = await connection.execute(
        text("SELECT 1 FROM journal_tags WHERE id = CAST(:tag_id AS uuid)"),
        {"tag_id": tag_id},
    )
    return row.fetchone() is not None


@pytest.mark.integration
class TestJournalTagOwnershipIsEnforced:
    """Another user's journal tag reads, and refuses writes, as a missing one."""

    @pytest.mark.parametrize(
        "request_spec",
        CROSS_USER_TAG_REQUESTS,
        ids=lambda spec: f"{spec.method} {spec.route}",
    )
    async def test_another_users_tag_reads_as_an_absent_one(
        self,
        request_spec: CrossUserRequest,
        integration_api_client,
        async_connection: AsyncConnection,
        foreign_journal: ForeignJournal,
    ) -> None:
        before = await _snapshot(async_connection, foreign_journal.journal_id)

        response = await integration_api_client.request(
            request_spec.method,
            request_spec.path(foreign_journal),
            json=request_spec.filled_body(foreign_journal),
        )

        assert response.status_code == 404, (
            f"{request_spec.method} {request_spec.route} answered "
            f"{response.status_code} for another user's tag: {response.text[:400]}"
        )
        assert OTHER_TAG not in response.text
        assert await _snapshot(async_connection, foreign_journal.journal_id) == before

    async def test_merging_your_tag_into_theirs_is_refused(
        self,
        integration_api_client,
        async_connection: AsyncConnection,
        foreign_journal: ForeignJournal,
    ) -> None:
        """The merge *target* is owner-checked too, and the source survives."""
        before = await _snapshot(async_connection, foreign_journal.journal_id)

        response = await integration_api_client.post(
            f"/api/journals/tags/{foreign_journal.attacker_tag_id}/merge",
            json={
                "data": {
                    "type": "journal-tags",
                    "attributes": {"target_tag_id": foreign_journal.assigned_tag_id},
                }
            },
        )

        assert response.status_code == 404, response.text[:400]
        assert OTHER_TAG not in response.text
        assert await _tag_exists(async_connection, foreign_journal.attacker_tag_id)
        assert await _snapshot(async_connection, foreign_journal.journal_id) == before

    async def test_their_tag_cannot_be_assigned_to_your_journal(
        self,
        integration_api_client,
        async_connection: AsyncConnection,
        foreign_journal: ForeignJournal,
    ) -> None:
        """The journal is the caller's, so only the tag's owner can refuse it."""
        response = await integration_api_client.post(
            f"/api/journals/{foreign_journal.attacker_journal_id}/relationships/tags",
            json={
                "data": {
                    "type": "journal-tag-assignment",
                    "attributes": {"tag_id": foreign_journal.unassigned_tag_id},
                }
            },
        )

        assert response.status_code == 404, response.text[:400]
        assert OTHER_UNASSIGNED_TAG not in response.text
        assert not await _assignment_exists(
            async_connection,
            foreign_journal.attacker_journal_id,
            foreign_journal.unassigned_tag_id,
        )

    async def test_their_tag_cannot_parent_a_new_tag(
        self, integration_api_client, foreign_journal: ForeignJournal
    ) -> None:
        response = await integration_api_client.post(
            "/api/journals/tags",
            json={
                "data": {
                    "type": "journal-tags",
                    "attributes": {
                        "name": "child-of-a-stranger",
                        "parent_id": foreign_journal.assigned_tag_id,
                    },
                }
            },
        )

        assert response.status_code == 404, response.text[:400]
        assert OTHER_TAG not in response.text

    async def test_the_tag_list_holds_only_your_tags(
        self, integration_api_client, foreign_journal: ForeignJournal
    ) -> None:
        response = await integration_api_client.get("/api/journals/tags")

        assert response.status_code == 200
        assert [tag["attributes"]["name"] for tag in response.json()["data"]] == [
            OWN_TAG
        ]

    async def test_a_name_another_user_holds_is_yours_to_create(
        self, integration_api_client, foreign_journal: ForeignJournal
    ) -> None:
        """Names are unique per owner: their tag does not block yours."""
        response = await integration_api_client.post(
            "/api/journals/tags",
            json={"data": {"type": "journal-tags", "attributes": {"name": OTHER_TAG}}},
        )

        assert response.status_code == 201, response.text[:400]
        assert response.json()["data"]["id"] != foreign_journal.assigned_tag_id

    async def test_filtering_by_their_tag_returns_nothing(
        self, integration_api_client, foreign_journal: ForeignJournal
    ) -> None:
        """Their journal carries the tag; the caller still sees no journal."""
        response = await integration_api_client.get(
            "/api/journals", params={"tag_ids": foreign_journal.assigned_tag_id}
        )

        assert response.status_code == 200
        assert response.json()["data"] == []
        assert OTHER_TITLE not in response.text


async def _contact_link_exists(
    connection: AsyncConnection, journal_id: int, contact_id: int
) -> bool:
    row = await connection.execute(
        text(
            "SELECT 1 FROM journal_contact_relationships "
            "WHERE journal_id = :journal_id AND contact_id = :contact_id"
        ),
        {"journal_id": journal_id, "contact_id": contact_id},
    )
    return row.fetchone() is not None


def _error_without_ids(response: Response, contact_id: int) -> list[dict[str, Any]]:
    """The JSON:API errors, minus the per-response error id and the contact id.

    Only ``ID <n>`` is masked: a bare substring replace would also rewrite the
    status whenever the contact id is a substring of it (contact 40 in "404").
    """
    return [
        {
            key: re.sub(rf"\bID {contact_id}\b", "ID <id>", str(value))
            for key, value in error.items()
            if key != "id"
        }
        for error in response.json()["errors"]
    ]


def _link_contact_body(contact_id: int) -> dict[str, Any]:
    return {
        "data": {
            "type": CONTACT_RELATIONSHIP_RESOURCE,
            "attributes": {
                "contact_id": str(contact_id),
                "relationship_type": PARTICIPANT,
            },
        }
    }


@pytest.mark.integration
class TestJournalContactOwnershipIsEnforced:
    """Another user's contact cannot join your journal, and says so as a missing one.

    The journal is the caller's, so only the contact's owner can refuse the link:
    a journal's people are the journal owner's contacts.
    """

    async def test_their_contact_cannot_join_your_journal(
        self,
        integration_api_client: AsyncClient,
        async_connection: AsyncConnection,
        foreign_journal: ForeignJournal,
    ) -> None:
        response = await integration_api_client.post(
            f"/api/journals/{foreign_journal.attacker_journal_id}"
            "/relationships/contacts",
            json=_link_contact_body(foreign_journal.contact_id),
        )

        assert response.status_code == 404, response.text[:400]
        assert OTHER_CONTACT not in response.text
        assert not await _contact_link_exists(
            async_connection,
            foreign_journal.attacker_journal_id,
            foreign_journal.contact_id,
        )

    async def test_their_contact_is_refused_exactly_as_a_missing_one(
        self,
        integration_api_client: AsyncClient,
        foreign_journal: ForeignJournal,
    ) -> None:
        route = (
            f"/api/journals/{foreign_journal.attacker_journal_id}"
            "/relationships/contacts"
        )
        missing_id = 999_999

        foreign = await integration_api_client.post(
            route, json=_link_contact_body(foreign_journal.contact_id)
        )
        absent = await integration_api_client.post(
            route, json=_link_contact_body(missing_id)
        )

        assert foreign.status_code == absent.status_code == 404
        assert "ID <id>" in str(_error_without_ids(foreign, foreign_journal.contact_id))
        assert _error_without_ids(
            foreign, foreign_journal.contact_id
        ) == _error_without_ids(absent, missing_id)


@pytest.mark.integration
class TestJournalTagOwnershipCoverageIsComplete:
    """Every journal route keyed by a tag id has a cross-user test."""

    def test_every_journal_tag_id_route_is_covered(self, test_settings) -> None:
        mounted = _mounted_journal_tag_id_routes(create_app(settings=test_settings))
        tested = {
            (spec.method, spec.route)
            for spec in (*CROSS_USER_REQUESTS, *CROSS_USER_TAG_REQUESTS)
        }

        uncovered = mounted - tested
        assert not uncovered, (
            "these journal tag-by-id operations have no ownership test: "
            f"{sorted(uncovered)}. Add each to CROSS_USER_TAG_REQUESTS."
        )
        stale = {(s.method, s.route) for s in CROSS_USER_TAG_REQUESTS} - mounted
        assert not stale, f"no longer served: {sorted(stale)}"
