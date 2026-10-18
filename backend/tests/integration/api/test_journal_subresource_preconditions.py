"""Every write to a journal's rows honours ``If-Match`` and hands back an ``ETag``.

The journal counterpart of ``test_subresource_preconditions.py``, which explains
the contract: a journal's tag covers its types, type data, contact
relationships and tag assignments, so a write to any of them is guarded by the
journal's tag and answers with the journal's new one.

The requests are the ownership suite's own, made against a journal the caller
owns. The coverage test compares the table with the app's routes, so a new
journal write fails until it is guarded or exempted with a reason.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.main import create_app
from tests.integration.api.test_journal_ownership import (
    CROSS_USER_REQUESTS,
    CrossUserRequest,
    ForeignJournal,
    _snapshot,
    foreign_journal,  # noqa: F401 - pytest fixture, used through own_journal
)
from tests.integration.contact_seeding import OTHER_USER_ID, TEST_USER_ID

STALE_ETAG = '"0000000000000000"'

JOURNAL_ROUTE = "/api/journals/{journal_id}"
TYPE_ROUTE = JOURNAL_ROUTE + "/types/{journal_type}"
CONTACT_RELATIONSHIPS = JOURNAL_ROUTE + "/relationships/contacts"
CONTACT_RELATIONSHIP = CONTACT_RELATIONSHIPS + "/{contact_id}/{relationship_type}"
TAG_ASSIGNMENTS = JOURNAL_ROUTE + "/relationships/tags"
SERIES_MEMBERSHIPS = JOURNAL_ROUTE + "/relationships/series"
ROUTES = JOURNAL_ROUTE + "/routes"
DISMISSALS = "/api/journals/incomplete-outdoor-activities/{journal_id}"

GUARDED: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", JOURNAL_ROUTE + "/types"),
        ("DELETE", TYPE_ROUTE),
        ("PUT", TYPE_ROUTE + "/data"),
        ("POST", CONTACT_RELATIONSHIPS),
        ("PATCH", CONTACT_RELATIONSHIP),
        ("DELETE", CONTACT_RELATIONSHIP),
        ("POST", TAG_ASSIGNMENTS),
        ("DELETE", TAG_ASSIGNMENTS + "/{tag_id}"),
    }
)

GUARDED_REQUESTS: tuple[CrossUserRequest, ...] = tuple(
    spec for spec in CROSS_USER_REQUESTS if (spec.method, spec.route) in GUARDED
)

OWN_RESOURCE = (
    "not part of the journal's version: it is its own resource, and writing it "
    "does not touch the journal"
)
UNGUARDED_BY_DESIGN: dict[tuple[str, str], str] = {
    ("PUT", JOURNAL_ROUTE): "covered by test_etag_concurrency.py",
    ("PATCH", JOURNAL_ROUTE): "covered by test_etag_concurrency.py",
    ("DELETE", JOURNAL_ROUTE): (
        "removes the whole aggregate: there is no later state for a stale "
        "client to overwrite"
    ),
    ("POST", JOURNAL_ROUTE + "/merge"): (
        "writes two aggregates under the merge's own lock protocol "
        "(both journals FOR UPDATE in id order)"
    ),
    ("POST", SERIES_MEMBERSHIPS): OWN_RESOURCE,
    ("DELETE", SERIES_MEMBERSHIPS + "/{series_id}"): OWN_RESOURCE,
    ("POST", ROUTES): OWN_RESOURCE,
    ("PUT", ROUTES + "/{route_id}"): OWN_RESOURCE,
    ("DELETE", ROUTES + "/{route_id}"): OWN_RESOURCE,
    ("POST", JOURNAL_ROUTE + "/tasks"): "creates a task: its own aggregate",
    ("POST", DISMISSALS + "/dismiss"): OWN_RESOURCE,
    ("POST", DISMISSALS + "/undismiss"): OWN_RESOURCE,
    (
        "DELETE",
        "/api/tasks/{task_id}/relationships/intermediate-journals/{journal_id}",
    ): ("writes the task, keyed on the task"),
}

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Long before any request, so a write that touches the journal moves its tag.
SEEDED_LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)


async def _hand_seeded_rows_to_caller(connection: AsyncConnection) -> None:
    """Make the caller the owner of every row the ownership fixture seeded."""
    owned_tables = (
        await connection.execute(
            text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE column_name = 'user_id' AND table_schema = current_schema() "
                "AND table_name IN ('journals', 'contacts', 'journal_tags', "
                "'journal_tag_assignments')"
            )
        )
    ).scalars()
    for table in owned_tables:
        await connection.execute(
            text(f"UPDATE {table} SET user_id = :me WHERE user_id = :them"),  # noqa: S608 - names from a fixed list
            {"me": TEST_USER_ID, "them": OTHER_USER_ID},
        )


@pytest.fixture
async def own_journal(
    async_connection: AsyncConnection,
    foreign_journal: ForeignJournal,  # noqa: F811 - the imported fixture
) -> ForeignJournal:
    """The ownership suite's furnished journal, owned by the caller."""
    await _hand_seeded_rows_to_caller(async_connection)
    await async_connection.execute(
        text("UPDATE journals SET updated_at = :then"),
        {"then": SEEDED_LONG_AGO},
    )
    return foreign_journal


async def _current_etag(client: AsyncClient, seeded: ForeignJournal) -> str:
    response = await client.get(f"/api/journals/{seeded.journal_id}")
    assert response.status_code == 200, response.text[:400]
    return response.headers["ETag"]


async def _send(
    client: AsyncClient,
    spec: CrossUserRequest,
    seeded: ForeignJournal,
    if_match: str,
) -> Response:
    return await client.request(
        spec.method,
        spec.path(seeded),
        json=spec.filled_body(seeded),
        headers={"If-Match": if_match},
    )


@pytest.mark.integration
class TestJournalRowWritesHonourIfMatch:
    """Each guarded route, under each kind of precondition."""

    @pytest.mark.parametrize(
        "spec", GUARDED_REQUESTS, ids=lambda spec: f"{spec.method} {spec.route}"
    )
    async def test_matching_tag_writes_and_answers_with_the_new_tag(
        self,
        spec: CrossUserRequest,
        integration_api_client: AsyncClient,
        own_journal: ForeignJournal,
    ) -> None:
        etag = await _current_etag(integration_api_client, own_journal)

        response = await _send(integration_api_client, spec, own_journal, etag)

        assert response.is_success, response.text[:400]
        assert response.headers.get("ETag") == await _current_etag(
            integration_api_client, own_journal
        )
        assert response.headers["ETag"] != etag

    @pytest.mark.parametrize(
        "spec", GUARDED_REQUESTS, ids=lambda spec: f"{spec.method} {spec.route}"
    )
    async def test_stale_tag_is_refused_and_writes_nothing(
        self,
        spec: CrossUserRequest,
        integration_api_client: AsyncClient,
        async_connection: AsyncConnection,
        own_journal: ForeignJournal,
    ) -> None:
        current = await _current_etag(integration_api_client, own_journal)
        before = await _snapshot(async_connection, own_journal.journal_id)

        response = await _send(integration_api_client, spec, own_journal, STALE_ETAG)

        assert response.status_code == 412, response.text[:400]
        error: dict[str, Any] = response.json()["errors"][0]
        assert error["code"] == "PRECONDITION_FAILED"
        assert error["meta"]["current_etag"] == current
        assert await _snapshot(async_connection, own_journal.journal_id) == before

    @pytest.mark.parametrize(
        "spec", GUARDED_REQUESTS, ids=lambda spec: f"{spec.method} {spec.route}"
    )
    async def test_no_precondition_writes_as_before(
        self,
        spec: CrossUserRequest,
        integration_api_client: AsyncClient,
        own_journal: ForeignJournal,
    ) -> None:
        """Unlike the contact suite's, the journal ownership suite has no owner
        replay to prove this already."""
        unconditional = await integration_api_client.request(
            spec.method, spec.path(own_journal), json=spec.filled_body(own_journal)
        )
        assert unconditional.is_success, unconditional.text[:400]

    @pytest.mark.parametrize(
        "spec", GUARDED_REQUESTS, ids=lambda spec: f"{spec.method} {spec.route}"
    )
    async def test_wildcard_writes(
        self,
        spec: CrossUserRequest,
        integration_api_client: AsyncClient,
        own_journal: ForeignJournal,
    ) -> None:
        response = await _send(integration_api_client, spec, own_journal, "*")

        assert response.is_success, response.text[:400]


def _mounted_journal_writes(app: Any) -> set[tuple[str, str]]:
    """Every write ``(method, path)`` whose path names a journal."""
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if "{journal_id}" in path
        for method in operations
        if method.upper() in WRITE_METHODS
    }


@pytest.mark.integration
class TestJournalPreconditionCoverageIsComplete:
    """The table is checked against the app, not against memory."""

    def test_every_journal_write_is_guarded_or_exempted(
        self, test_settings: Any
    ) -> None:
        mounted = _mounted_journal_writes(create_app(settings=test_settings))
        unaccounted = mounted - GUARDED - set(UNGUARDED_BY_DESIGN)

        assert not unaccounted, (
            "these journal writes take no If-Match: "
            f"{sorted(unaccounted)}. Guard each (add it to GUARDED), or add it "
            "to UNGUARDED_BY_DESIGN with the reason it does not belong."
        )

    def test_the_table_names_only_served_routes_with_a_request(
        self, test_settings: Any
    ) -> None:
        mounted = _mounted_journal_writes(create_app(settings=test_settings))
        listed = GUARDED | set(UNGUARDED_BY_DESIGN)

        assert not listed - mounted, f"no longer served: {sorted(listed - mounted)}"
        assert {(s.method, s.route) for s in GUARDED_REQUESTS} == GUARDED
