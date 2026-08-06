"""Integration tests for ``POST /api/journals/{journal_id}/tasks``.

Phase 4 proved the invariants against the service. What this file proves is that
the **endpoint inherits them** — which a shared service is not evidence of on its
own, since a controller can validate too little, catch too much, or answer with a
status that contradicts the domain. So the whole rejection matrix is asserted
again here, one test per violated invariant, at the surface a client actually
reaches.

Three properties are only observable from out here:

- **the creating journal is the path journal**, never a body field, so a client
  cannot anchor a task to a journal it did not come from;
- **the write is committed before the response**, because the service owns the
  unit of work and the controller opens none — the row is queried back after the
  request returns;
- **the status code for each rejection**, including the phase's deliberate
  decision that a due journal that is absent or not yours answers 404 with the
  payload naming *which* anchor.

The timezone pair is dated rather than clocked. ``now`` is deliberately
unreachable from a request, so a test cannot stand either side of local midnight
here; instead it asserts the *journal's* rendered date, which is a pure function
of the journal's start and the user's timezone. Kiritimati (+14) and Midway (-11)
are 25 hours apart, so their local dates differ at every instant — no clock, no
race, and a UTC reading fails both.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from tests.integration.tasks.task_seeding import (
    COUNT_CONTACT_LINKS,
    COUNT_TASKS,
    FIXED_PAST_INSTANT,
    OTHER_USER_ID,
    USER_ID,
    count,
    create_contact,
    create_journal,
)


def _body(**attributes: object) -> dict[str, object]:
    return {"data": {"type": "tasks", "attributes": attributes}}


def _error(response_json: dict[str, object]) -> dict[str, object]:
    errors = response_json["errors"]
    assert isinstance(errors, list)
    assert len(errors) == 1
    first: dict[str, object] = errors[0]
    return first


@pytest.mark.integration
class TestCreateTaskEndpoint:
    """The happy paths, and what the response says about them."""

    async def test_creates_a_task_anchored_to_the_path_journal(
        self,
        authenticated_client: AsyncClient,
        task_anchors: tuple[int, int],
    ):
        """The creating journal is the one in the URL — the body cannot name it."""
        creating_id, due_id = task_anchors

        response = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(text="print the permit", due_journal_id=due_id),
        )

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["type"] == "tasks"
        assert int(data["id"]) > 0
        assert data["attributes"]["text"] == "print the permit"
        assert data["attributes"]["creating_journal_id"] == creating_id
        assert data["attributes"]["due_journal_id"] == due_id
        assert data["attributes"]["status"] == "not_done"

    async def test_the_row_is_committed_before_the_response(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The service's unit of work commits; the controller opens none.

        Reading the row back *after* the response is the only way to tell a
        committed write from one still sitting in an open transaction that the
        connection provider will roll back at teardown.
        """
        creating_id, due_id = task_anchors

        response = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(text="print the permit", due_journal_id=due_id),
        )
        assert response.status_code == 201

        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 1

    async def test_accepts_the_same_journal_as_both_anchors(
        self,
        authenticated_client: AsyncClient,
        journal_repository: SqlJournalRepository,
    ):
        """Invariant 6: creating and due may be one journal, if it is future-dated."""
        journal_id = await create_journal(
            journal_repository, title="Next week's trip", days_offset=7
        )

        response = await authenticated_client.post(
            f"/api/journals/{journal_id}/tasks",
            json=_body(text="pack the ropes", due_journal_id=journal_id),
        )

        assert response.status_code == 201
        attributes = response.json()["data"]["attributes"]
        assert attributes["creating_journal_id"] == journal_id
        assert attributes["due_journal_id"] == journal_id

    async def test_links_the_requested_contacts(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        first = await create_contact(async_connection, first_name="Sarah")
        second = await create_contact(async_connection, first_name="Tom")

        response = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(
                text="split the gear",
                due_journal_id=due_id,
                contact_ids=[first, second],
            ),
        )

        assert response.status_code == 201
        assert await count(async_connection, COUNT_CONTACT_LINKS, {}) == 2


@pytest.mark.integration
class TestUnreachableAnchorsAnswer404:
    """The phase's deliberate status decision, and what the payload adds to it."""

    async def test_an_absent_due_journal_names_the_due_anchor(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """404 is ambiguous on its own; the payload is what disambiguates it.

        The path journal exists, so a client reading only the status line could
        conclude it did not. The error names the *due* anchor and its id instead.
        """
        creating_id, _ = task_anchors

        response = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(text="print the permit", due_journal_id=999_999),
        )

        assert response.status_code == 404
        error = _error(response.json())
        assert error["code"] == "TASK_ANCHOR_JOURNAL_NOT_FOUND"
        assert "due journal (ID 999999)" in str(error["detail"])
        assert str(creating_id) not in str(error["detail"])
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_another_users_due_journal_reads_as_an_absent_one(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Phase 4's indistinguishability guarantee survives the surface.

        Both rejections must be byte-identical once the ids are stripped, or a
        rejected create becomes a way to probe for another user's journals.
        """
        creating_id, _ = task_anchors
        foreign_id = await create_journal(
            journal_repository,
            title="Somebody else's trip",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )

        foreign = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(text="print the permit", due_journal_id=foreign_id),
        )
        absent = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(text="print the permit", due_journal_id=999_999),
        )

        assert foreign.status_code == absent.status_code == 404
        foreign_error, absent_error = _error(foreign.json()), _error(absent.json())
        assert foreign_error["code"] == absent_error["code"]
        assert str(foreign_error["detail"]).replace(str(foreign_id), "X") == str(
            absent_error["detail"]
        ).replace("999999", "X")
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_another_users_path_journal_is_rejected_as_the_creating_anchor(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """A task can never span owners, whichever anchor the intruder is."""
        _, due_id = task_anchors
        foreign_id = await create_journal(
            journal_repository,
            title="Somebody else's day",
            user_id=OTHER_USER_ID,
        )

        response = await authenticated_client.post(
            f"/api/journals/{foreign_id}/tasks",
            json=_body(text="print the permit", due_journal_id=due_id),
        )

        assert response.status_code == 404
        error = _error(response.json())
        assert error["code"] == "TASK_ANCHOR_JOURNAL_NOT_FOUND"
        assert f"creating journal (ID {foreign_id})" in str(error["detail"])
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0


@pytest.mark.integration
class TestTheFutureDatedRuleReachesTheEndpoint:
    """Invariant 4 at the surface, including whose timezone decides it."""

    async def test_a_past_due_journal_is_rejected_with_both_dates(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, _ = task_anchors
        past_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )

        response = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(text="too late", due_journal_id=past_id),
        )

        assert response.status_code == 400
        error = _error(response.json())
        assert error["code"] == "TASK_DUE_JOURNAL_NOT_FUTURE"
        assert "not after today" in str(error["detail"])
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    @pytest.mark.parametrize(
        ("timezone", "expected_date"),
        [
            ("Pacific/Kiritimati", "2020-01-02"),
            ("Pacific/Midway", "2020-01-01"),
        ],
    )
    async def test_the_journals_date_is_rendered_in_the_users_timezone(
        self,
        authenticated_client: AsyncClient,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
        task_anchors: tuple[int, int],
        timezone: str,
        expected_date: str,
    ):
        """A UTC reading would say 2020-01-01 to both of them, and be wrong once.

        The two zones are 25 hours apart, so one instant is never the same date
        in both — which makes this an assertion about the day boundary that does
        not depend on when the test runs.
        """
        creating_id, _ = task_anchors
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=timezone)
        )
        past_id = await create_journal(
            journal_repository, title="New Year 2020", start=FIXED_PAST_INSTANT
        )

        response = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(text="too late", due_journal_id=past_id),
        )

        assert response.status_code == 400
        assert f"is dated {expected_date}" in str(_error(response.json())["detail"])


@pytest.mark.integration
class TestRejectedBodies:
    """What a client may not send, and what happens when it does."""

    async def test_an_unknown_contact_is_rejected_and_nothing_is_written(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors

        response = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(
                text="split the gear", due_journal_id=due_id, contact_ids=[999_999]
            ),
        )

        assert response.status_code == 404
        assert _error(response.json())["code"] == "CONTACT_NOT_FOUND"
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0
        assert await count(async_connection, COUNT_CONTACT_LINKS, {}) == 0

    async def test_empty_text_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors

        response = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(text="   ", due_journal_id=due_id),
        )

        assert response.status_code == 400
        assert _error(response.json())["code"] == "TASK_VALIDATION_ERROR"
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_a_body_carrying_now_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Invariant 4 is not opt-out for any client.

        ``now`` is the seam the rule is judged against. Rejecting the field
        outright — rather than ignoring it — is what stops a future wiring change
        from quietly handing it to the service.
        """
        creating_id, due_id = task_anchors

        response = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(
                text="cheat the clock",
                due_journal_id=due_id,
                now="2020-01-01T00:00:00+00:00",
            ),
        )

        assert response.status_code == 400
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_a_body_offering_a_bare_date_is_rejected(
        self,
        authenticated_client: AsyncClient,
        task_anchors: tuple[int, int],
    ):
        """A task is due in a journal; a date would imply creating one."""
        creating_id, due_id = task_anchors

        response = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(text="book it", due_journal_id=due_id, due_date="2026-09-01"),
        )

        assert response.status_code == 400

    async def test_a_body_naming_the_creating_journal_is_rejected(
        self,
        authenticated_client: AsyncClient,
        task_anchors: tuple[int, int],
    ):
        """The path is the only way to say where a task arose."""
        creating_id, due_id = task_anchors

        response = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(
                text="book it",
                due_journal_id=due_id,
                creating_journal_id=due_id,
            ),
        )

        assert response.status_code == 400

    async def test_a_body_carrying_now_beside_the_data_member_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The request envelope is guarded too, not just what is inside it.

        Raised in review: the attributes and data models forbade extras while
        the outermost level still ignored them, so ``now`` beside ``data`` was
        dropped rather than refused.
        """
        creating_id, due_id = task_anchors

        response = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json={
                "data": {
                    "type": "tasks",
                    "attributes": {"text": "cheat the clock", "due_journal_id": due_id},
                },
                "now": "2020-01-01T00:00:00+00:00",
            },
        )

        assert response.status_code == 400
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_a_body_declaring_another_resource_type_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A client that declares "contacts" must not end up creating a task.

        Raised in review: the type was previously accepted and silently answered
        with `"tasks"`, so a generic JSON:API client could perform a mutation on
        a resource type it never asked for.
        """
        creating_id, due_id = task_anchors

        response = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json={
                "data": {
                    "type": "contacts",
                    "attributes": {"text": "book it", "due_journal_id": due_id},
                }
            },
        )

        assert response.status_code == 400
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0
