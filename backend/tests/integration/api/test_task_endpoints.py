"""Integration tests for the task endpoints.

``POST /api/journals/{journal_id}/tasks`` creates; ``PATCH /api/tasks/{task_id}``
rewords a task, changes its status, or both; ``DELETE /api/tasks/{task_id}``
destroys one. The last two are *member* routes with no collection beside them:
the specification is explicit that no screen lists every task, and none of these
operations involves a journal at all, so reaching a task through one would be a
fiction.

Phase 4 proved the invariants against the service. What this file proves is that
the **endpoint inherits them** — which a shared service is not evidence of on its
own, since a controller can validate too little, catch too much, or answer with a
status that contradicts the domain. So the whole rejection matrix is asserted
again here, one test per violated invariant, at the surface a client actually
reaches.

Three properties are only observable from out here:

- **the creating journal is the path journal**, never a body field, so a client
  cannot anchor a task to a journal it did not come from;
- **the write has happened before the response**, queried back after the request
  returns rather than read off the payload. Note what this does *not* show: the
  fixture marks the connection, so ``unit_of_work`` uses a SAVEPOINT and the row
  is visible whether or not the service committed. The unit of work itself is
  asserted in ``tests/integration/tasks/`` where it is observable — the claim
  here was previously overstated and is corrected;
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

from datetime import date, timedelta

import pytest
from core_shared.models.history import Provenance
from core_shared.models.journals import JournalNotFoundError
from core_shared.models.journals.event_state import EventState
from core_shared.models.tasks import TaskStatus
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from app.core.tasks.models.events import contact_field_name
from tests.integration.tasks.task_seeding import (
    COUNT_CONTACT_LINKS,
    COUNT_CONTACT_LINKS_FOR_TASK,
    COUNT_INTERMEDIATE_JOURNALS,
    COUNT_TASKS,
    FIXED_PAST_INSTANT,
    OTHER_USER_ID,
    USER_ID,
    backdate_updated_at,
    count,
    create_contact,
    create_journal,
    create_task,
    delete_contact,
    delete_journal,
    intermediate_journal_ids,
    link_contact,
    link_intermediate_journal,
    linked_contact_ids,
    mark_journal_as_event,
    stored_anchors,
    stored_status,
    stored_text,
    stored_updated_at,
    task_events,
    task_exists,
)


def _body(**attributes: object) -> dict[str, object]:
    return {"data": {"type": "tasks", "attributes": attributes}}


def _update_body(task_id: int, **attributes: object) -> dict[str, object]:
    return {"data": {"type": "tasks", "id": str(task_id), "attributes": attributes}}


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

    async def test_the_row_is_written_by_the_time_the_response_returns(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The row exists once the client has been answered.

        Renamed and re-scoped: this previously claimed to distinguish a
        committed write from an open one, which it cannot. The fixture marks the
        connection, so ``unit_of_work`` emulates the commit with a SAVEPOINT and
        this read sees the row either way. The unit of work is asserted where it
        is observable — ``TestTheWriteIsAUnitOfWork`` in
        ``tests/integration/tasks/test_task_service_set_status_integration.py``.
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


@pytest.mark.integration
class TestUpdateTaskStatusEndpoint:
    """``PATCH /api/tasks/{task_id}``: the lifecycle at the surface."""

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            ("not_done", "done"),
            ("not_done", "cancelled"),
            ("done", "not_done"),
            ("done", "cancelled"),
        ],
    )
    async def test_each_permitted_transition_is_accepted(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        current: str,
        target: str,
    ):
        """Including done → not done: the specification calls done reversible."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus(current),
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}", json=_update_body(task_id, status=target)
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["type"] == "tasks"
        assert data["id"] == str(task_id)
        assert data["attributes"]["status"] == target
        assert data["attributes"]["creating_journal_id"] == creating_id
        assert data["attributes"]["due_journal_id"] == due_id

    async def test_the_new_status_is_written_by_the_time_the_response_returns(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The row is changed by the time the client is answered.

        **This does not prove the write was committed**, and no assertion out
        here can. The fixture owns an outer transaction and marks the
        connection, so ``unit_of_work`` stands a SAVEPOINT in for the commit and
        this read would see the row either way — deleting ``@transactional``
        leaves this test green. The unit of work is proved where it is
        observable, in ``TestTheWriteIsAUnitOfWork`` in
        ``tests/integration/tasks/test_task_service_set_status_integration.py``,
        by watching the transaction open around the repository call. What this
        test does own is the surface half: the controller passed the request
        connection through and the write happened before the response, rather
        than being deferred to some later teardown.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}", json=_update_body(task_id, status="done")
        )
        assert response.status_code == 200

        assert await stored_status(async_connection, task_id) == "done"

    async def test_no_journal_link_is_created(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Marking a task done or cancelled requires no journal and links none."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        for target in ("done", "not_done", "cancelled"):
            response = await authenticated_client.patch(
                f"/api/tasks/{task_id}", json=_update_body(task_id, status=target)
            )
            assert response.status_code == 200

        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    async def test_setting_the_status_a_task_already_has_changes_nothing(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Idempotent, including on a cancelled task — that is not a reopening."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.CANCELLED,
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}", json=_update_body(task_id, status="cancelled")
        )

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["status"] == "cancelled"
        assert await stored_status(async_connection, task_id) == "cancelled"


@pytest.mark.integration
class TestRefusedTransitionsAnswer409:
    """Leaving cancelled is a conflict with the task's state, not a bad request."""

    @pytest.mark.parametrize("target", ["not_done", "done"])
    async def test_leaving_cancelled_is_refused_and_says_how_to_reopen(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        target: str,
    ):
        """A refusal a client cannot act on is worse than no answer at all."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.CANCELLED,
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}", json=_update_body(task_id, status=target)
        )

        assert response.status_code == 409
        error = _error(response.json())
        assert error["code"] == "TASK_STATUS_TRANSITION_REFUSED"
        assert "retarget" in str(error["detail"]).lower()
        assert await stored_status(async_connection, task_id) == "cancelled"


@pytest.mark.integration
class TestUnreachableTasksAnswer404:
    """Somebody else's task is invisible, not merely forbidden."""

    async def test_another_users_task_reads_as_an_absent_one(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Byte-identical once the ids are stripped, and the row is untouched.

        A distinguishable answer here would turn the endpoint into a way to ask
        whether a given task id belongs to somebody.
        """
        foreign_journal = await create_journal(
            journal_repository,
            title="Somebody else's day",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )
        foreign_task = await create_task(
            async_connection,
            creating_journal_id=foreign_journal,
            due_journal_id=foreign_journal,
            user_id=OTHER_USER_ID,
        )

        foreign = await authenticated_client.patch(
            f"/api/tasks/{foreign_task}", json=_update_body(foreign_task, status="done")
        )
        absent = await authenticated_client.patch(
            "/api/tasks/999999", json=_update_body(999_999, status="done")
        )

        assert foreign.status_code == absent.status_code == 404
        foreign_error, absent_error = _error(foreign.json()), _error(absent.json())
        assert foreign_error["code"] == absent_error["code"] == "TASK_NOT_FOUND"
        assert str(foreign_error["detail"]).replace(str(foreign_task), "X") == str(
            absent_error["detail"]
        ).replace("999999", "X")
        assert await stored_status(async_connection, foreign_task) == "not_done"


@pytest.mark.integration
class TestUpdateTaskTextEndpoint:
    """``PATCH /api/tasks/{task_id}``: rewording, in any status.

    The same route as the status change, because JSON:API sends the attributes
    that changed and a client may well have changed both. That is the reason the
    two are applied by one service call rather than two: a request that reworded
    and completed a task in two calls could have half of it applied.
    """

    @pytest.mark.parametrize("status", ["not_done", "done", "cancelled"])
    async def test_the_text_is_editable_in_every_status(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        status: str,
    ):
        """Including cancelled: a retired commitment can still be reworded."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus(status),
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}", json=_update_body(task_id, text="reworded")
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["attributes"]["text"] == "reworded"
        assert data["attributes"]["status"] == status
        assert data["attributes"]["creating_journal_id"] == creating_id
        assert data["attributes"]["due_journal_id"] == due_id

    async def test_the_new_text_is_written_by_the_time_the_response_returns(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """As with the status endpoint, this shows the write happened before the
        client was answered — not that it committed. See that test's docstring."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}", json=_update_body(task_id, text="reworded")
        )
        assert response.status_code == 200

        assert await stored_text(async_connection, task_id) == "reworded"

    async def test_text_and_status_can_arrive_together(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """One request, one row change — the reason a single method owns both."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}",
            json=_update_body(task_id, text="reworded", status="done"),
        )

        assert response.status_code == 200
        assert await stored_text(async_connection, task_id) == "reworded"
        assert await stored_status(async_connection, task_id) == "done"

    async def test_a_refused_status_takes_the_text_edit_with_it(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """One request is one decision: a refused half refuses the whole.

        This is the property the single-service-call design exists to give, so
        it is asserted at the surface a client actually reaches rather than only
        against the service. A controller that applied the text first and then
        asked for the status would answer 409 having already reworded the
        task — half the request applied, and no way for the client to know
        which half.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print the permit",
            status=TaskStatus.CANCELLED,
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}",
            json=_update_body(task_id, text="reworded", status="done"),
        )

        assert response.status_code == 409
        assert _error(response.json())["code"] == "TASK_STATUS_TRANSITION_REFUSED"
        assert await stored_text(async_connection, task_id) == "print the permit"
        assert await stored_status(async_connection, task_id) == "cancelled"

    async def test_blank_text_beside_a_valid_status_refuses_both(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The mirror of the above: the text is the invalid half this time."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print the permit",
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}",
            json=_update_body(task_id, text="   ", status="done"),
        )

        assert response.status_code == 400
        assert await stored_text(async_connection, task_id) == "print the permit"
        assert await stored_status(async_connection, task_id) == "not_done"

    async def test_a_lapsed_task_can_still_be_reworded(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The due journal is never re-read, so its date cannot block a typo fix."""
        past_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        task_id = await create_task(
            async_connection, creating_journal_id=past_id, due_journal_id=past_id
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}", json=_update_body(task_id, text="reworded")
        )

        assert response.status_code == 200
        assert await stored_text(async_connection, task_id) == "reworded"

    async def test_no_journal_link_is_created_by_an_edit(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Intermediate links are explicit only; editing infers none."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}", json=_update_body(task_id, text="reworded")
        )
        assert response.status_code == 200

        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    @pytest.mark.parametrize("blank", ["", "   "])
    async def test_blank_text_is_rejected_and_the_row_is_unchanged(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        blank: str,
    ):
        """The domain owns what an acceptable text is, and answers 400 for both
        surfaces rather than the schema refusing it a second way."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print the permit",
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}", json=_update_body(task_id, text=blank)
        )

        assert response.status_code == 400
        assert _error(response.json())["code"] == "TASK_VALIDATION_ERROR"
        assert await stored_text(async_connection, task_id) == "print the permit"

    async def test_another_users_task_reads_as_an_absent_one(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Byte-identical once the ids are stripped, and the text is untouched."""
        foreign_journal = await create_journal(
            journal_repository,
            title="Somebody else's day",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )
        foreign_task = await create_task(
            async_connection,
            creating_journal_id=foreign_journal,
            due_journal_id=foreign_journal,
            text="not yours",
            user_id=OTHER_USER_ID,
        )

        foreign = await authenticated_client.patch(
            f"/api/tasks/{foreign_task}",
            json=_update_body(foreign_task, text="reworded"),
        )
        absent = await authenticated_client.patch(
            "/api/tasks/999999", json=_update_body(999_999, text="reworded")
        )

        assert foreign.status_code == absent.status_code == 404
        foreign_error, absent_error = _error(foreign.json()), _error(absent.json())
        assert foreign_error["code"] == absent_error["code"] == "TASK_NOT_FOUND"
        assert str(foreign_error["detail"]).replace(str(foreign_task), "X") == str(
            absent_error["detail"]
        ).replace("999999", "X")
        assert await stored_text(async_connection, foreign_task) == "not yours"


@pytest.mark.integration
class TestDeleteTaskEndpoint:
    """``DELETE /api/tasks/{task_id}``: the exception, not the ordinary action.

    The specification's stance — cancel is normal, delete is for genuine
    mistakes — is carried by what the surfaces *say*, since an endpoint cannot
    refuse to be the exception. What it can guarantee is the blast radius: the
    task and its link rows, and nothing else.
    """

    async def test_deleting_answers_204_and_removes_the_row(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """204 rather than a body: there is no resource left to return."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.delete(f"/api/tasks/{task_id}")

        assert response.status_code == 204
        assert response.content == b""
        assert not await task_exists(async_connection, task_id)

    async def test_the_link_rows_go_and_the_journals_and_contacts_stay(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The acceptance criterion, at the surface a client reaches.

        Both anchors survive in particular: they are journals ITER18-002 refuses
        to delete *because* a task points at them, and deleting the task is the
        supported way to unblock that — not a reason to lose the journals too.
        """
        creating_id, due_id = task_anchors
        mentioned_id = await create_journal(
            journal_repository, title="Where it came up", days_offset=3
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        contact_id = await create_contact(async_connection)
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mentioned_id
        )
        await link_contact(async_connection, task_id=task_id, contact_id=contact_id)

        response = await authenticated_client.delete(f"/api/tasks/{task_id}")

        assert response.status_code == 204
        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 0
        assert await count(async_connection, COUNT_CONTACT_LINKS, {}) == 0
        for journal_id in (creating_id, due_id, mentioned_id):
            assert await journal_repository.find_by_id(journal_id) is not None
        assert (
            await count(
                async_connection,
                "SELECT COUNT(*) FROM contacts WHERE id = :contact_id",
                {"contact_id": contact_id},
            )
            == 1
        )

    async def test_other_tasks_are_untouched(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A sibling sharing both anchors is not collateral damage."""
        creating_id, due_id = task_anchors
        doomed = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        survivor = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="somebody else's problem",
        )

        response = await authenticated_client.delete(f"/api/tasks/{doomed}")

        assert response.status_code == 204
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 1
        assert (
            await stored_text(async_connection, survivor) == "somebody else's problem"
        )

    async def test_deleting_twice_answers_404_the_second_time(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A 204 on a task that was not there would mislead a retrying client."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        first = await authenticated_client.delete(f"/api/tasks/{task_id}")
        second = await authenticated_client.delete(f"/api/tasks/{task_id}")

        assert first.status_code == 204
        assert second.status_code == 404
        assert _error(second.json())["code"] == "TASK_NOT_FOUND"

    async def test_another_users_task_reads_as_an_absent_one(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Indistinguishable, and — the half a 404 alone would not show — intact."""
        foreign_journal = await create_journal(
            journal_repository,
            title="Somebody else's day",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )
        foreign_task = await create_task(
            async_connection,
            creating_journal_id=foreign_journal,
            due_journal_id=foreign_journal,
            user_id=OTHER_USER_ID,
        )

        foreign = await authenticated_client.delete(f"/api/tasks/{foreign_task}")
        absent = await authenticated_client.delete("/api/tasks/999999")

        assert foreign.status_code == absent.status_code == 404
        foreign_error, absent_error = _error(foreign.json()), _error(absent.json())
        assert foreign_error["code"] == absent_error["code"] == "TASK_NOT_FOUND"
        assert str(foreign_error["detail"]).replace(str(foreign_task), "X") == str(
            absent_error["detail"]
        ).replace("999999", "X")
        assert await task_exists(async_connection, foreign_task)


@pytest.mark.integration
class TestRejectedUpdateBodies:
    """What a client may not send to the update endpoint."""

    @pytest.mark.parametrize(
        "attributes",
        [
            {"status": "in_progress"},
            {"status": "done", "due_journal_id": 9},
            {"status": "done", "now": "2020-01-01T00:00:00+00:00"},
            {},
        ],
        ids=["unknown status", "due journal", "now", "no attributes"],
    )
    async def test_rejected_attributes_leave_the_status_alone(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        attributes: dict[str, object],
    ):
        """Retargeting belongs to its own phase; there is no fourth status, no
        ``now``, and a body naming no change at all is a malformed request."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}", json=_update_body(task_id, **attributes)
        )

        assert response.status_code == 400
        assert await stored_status(async_connection, task_id) == "not_done"

    async def test_a_body_carrying_now_at_the_request_root_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """All three nesting levels are guarded, as the create request learned."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}",
            json={
                "data": {
                    "type": "tasks",
                    "id": str(task_id),
                    "attributes": {"status": "done"},
                },
                "now": "2020-01-01T00:00:00+00:00",
            },
        )

        assert response.status_code == 400
        assert await stored_status(async_connection, task_id) == "not_done"

    async def test_a_body_declaring_another_resource_type_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}",
            json={
                "data": {
                    "type": "contacts",
                    "id": str(task_id),
                    "attributes": {"status": "done"},
                }
            },
        )

        assert response.status_code == 400
        assert await stored_status(async_connection, task_id) == "not_done"

    async def test_a_body_id_that_disagrees_with_the_path_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Two ids naming different tasks is a request nobody can answer safely.

        Preferring the path silently would let a client change a task it
        believes it is not touching; neither row may move.
        """
        creating_id, due_id = task_anchors
        target_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        other_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="somebody else's problem",
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{target_id}", json=_update_body(other_id, status="done")
        )

        assert response.status_code == 400
        assert _error(response.json())["code"] == "TASK_VALIDATION_ERROR"
        assert await stored_status(async_connection, target_id) == "not_done"
        assert await stored_status(async_connection, other_id) == "not_done"


def _retarget_body(due_journal_id: object, **attributes: object) -> dict[str, object]:
    return {
        "data": {
            "type": "task-retarget",
            "attributes": {"due_journal_id": due_journal_id, **attributes},
        }
    }


@pytest.mark.integration
class TestRetargetEndpoint:
    """``POST /api/tasks/{task_id}/retarget``: the deadline moves, the trail stays.

    An action sub-resource rather than a field on the status ``PATCH``, for the
    reason ``POST /api/journals/{id}/merge`` is one: a retarget is not an
    assignment. It forces the status to *not done* and writes a link row, so a
    body able to carry a ``status`` alongside a ``due_journal_id`` would have two
    answers and no rule for choosing between them.

    Phase 7 proved the rules against the service. What this file proves is that
    the **endpoint inherits them**, which a shared service is not evidence of:
    the whole matrix is asserted again at the surface a client reaches.

    **Trails of more than one journal are compared sorted.** The port promises
    oldest link first and orders by ``created_at``, but every request in a test
    shares the fixture's single connection and therefore its transaction
    timestamp — so ``created_at`` ties and the tie-break decides. Asserting the
    tie-break's order would be asserting an artefact of the fixture rather than
    a property of the surface; the membership and the *count* are what the
    de-duplication claim is about.
    """

    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_a_retarget_lands_the_task_not_done_on_the_new_journal(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        status: TaskStatus,
    ):
        """Whatever it was before — including *cancelled*, which ``PATCH`` cannot leave.

        This is the specification's *"retargeting always leaves the task not
        done"* asserted per starting status, because "whatever the current
        status" is itself the claim.
        """
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget",
            json=_retarget_body(later_id, acknowledge_reopen=True),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["type"] == "tasks"
        assert data["id"] == str(task_id)
        assert data["attributes"]["status"] == "not_done"
        assert data["attributes"]["due_journal_id"] == later_id
        assert data["attributes"]["creating_journal_id"] == creating_id
        assert await stored_status(async_connection, task_id) == "not_done"
        assert await stored_anchors(async_connection, task_id) == (
            creating_id,
            later_id,
        )

    async def test_the_response_carries_the_journal_the_task_just_left(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The phase's second criterion, asserted on the payload rather than the row.

        A caller that had to make a second request to discover the trail would
        not have been shown it — and the specification's third success criterion
        is that a user moving a deadline *"still see[s] the trail of journals it
        passed through"*.
        """
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(later_id)
        )

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["intermediate_journal_ids"] == [
            due_id
        ]

    async def test_a_repeatedly_deferred_task_accumulates_its_trail(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Three hops, and the payload shows every journal the task passed through."""
        creating_id, due_id = task_anchors
        second = await create_journal(
            journal_repository, title="Two weeks out", days_offset=14
        )
        third = await create_journal(
            journal_repository, title="Three weeks out", days_offset=21
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        first_hop = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(second)
        )
        second_hop = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(third)
        )

        assert (first_hop.status_code, second_hop.status_code) == (200, 200)
        trail = second_hop.json()["data"]["attributes"]["intermediate_journal_ids"]
        assert sorted(trail) == sorted([due_id, second])

    async def test_returning_to_a_journal_already_in_the_trail_adds_no_duplicate(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Deferral is not always forwards, and the link table has one row per pair.

        Nothing is unlinked either: the journal it returns *from* stays in the
        trail, because it really was previously due.
        """
        creating_id, due_id = task_anchors
        second = await create_journal(
            journal_repository, title="Two weeks out", days_offset=14
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        # Out to the later journal, back to the original, and out again — so the
        # third hop leaves a journal the trail already holds.
        for target in (second, due_id):
            assert (
                await authenticated_client.post(
                    f"/api/tasks/{task_id}/retarget", json=_retarget_body(target)
                )
            ).status_code == 200
        final = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(second)
        )

        assert final.status_code == 200
        trail = final.json()["data"]["attributes"]["intermediate_journal_ids"]
        assert sorted(trail) == sorted([due_id, second])
        # Against the live composite primary key, not just the payload: three
        # hops, two journals, two rows.
        assert sorted(await intermediate_journal_ids(async_connection, task_id)) == (
            sorted([due_id, second])
        )

    async def test_a_lapsed_task_is_resurrected_and_keeps_the_passed_journal(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The journal being *left* is never judged, which is what makes this work.

        A lapsed task is one whose due journal has passed. The specification's
        fourth success criterion is that the user can find it on that journal and
        resurrect it — so the past journal cannot be re-validated on the way out,
        and it stays in the trail afterwards.
        """
        creating_id, _ = task_anchors
        passed_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        future_id = await create_journal(
            journal_repository, title="Next week", days_offset=7
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=passed_id,
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(future_id)
        )

        assert response.status_code == 200
        attributes = response.json()["data"]["attributes"]
        assert attributes["due_journal_id"] == future_id
        assert attributes["intermediate_journal_ids"] == [passed_id]

    async def test_the_creating_journal_is_a_legitimate_target(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Invariant 6 holds on a retarget as it does on creation."""
        journal_id = await create_journal(
            journal_repository, title="Next week's trip", days_offset=7
        )
        other_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=journal_id,
            due_journal_id=other_id,
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(journal_id)
        )

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["due_journal_id"] == journal_id

    async def test_retargeting_onto_the_current_due_journal_writes_nothing(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A no-op, mirroring the status endpoint's same-status no-op.

        Nothing is being *set*, so nothing is validated and nothing is written —
        which is what keeps a **lapsed** task's own journal answerable rather
        than being refused for having passed.

        **The timestamp is backdated first, without which the assertion below
        could not fail.** ``updated_at`` is written with ``now()``, which in
        PostgreSQL is the *transaction* timestamp, and every request in a test
        shares the fixture's single transaction — so an insert-time default and
        an update-time ``now()`` are the identical value, and "it did not move"
        holds whether or not anything was written. Backdating breaks the tie.
        A *cancelled* task is used so the status is a second, independent
        witness: any path but the no-op would have written *not done* over it.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.CANCELLED,
        )
        backdated = await backdate_updated_at(async_connection, task_id)

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(due_id)
        )

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["status"] == "cancelled"
        assert await stored_status(async_connection, task_id) == "cancelled"
        assert await stored_anchors(async_connection, task_id) == (creating_id, due_id)
        assert await stored_updated_at(async_connection, task_id) == backdated
        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    async def test_a_real_retarget_does_move_updated_at(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The other half of the pair, without which the no-op proves nothing.

        A backdated timestamp that never moves is equally consistent with "the
        no-op worked" and "no write ever reaches this column".
        """
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        backdated = await backdate_updated_at(async_connection, task_id)

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(later_id)
        )

        assert response.status_code == 200
        assert await stored_updated_at(async_connection, task_id) > backdated


@pytest.mark.integration
class TestReopeningADoneTaskNeedsAcknowledging:
    """The phase's third criterion: a refusal a surface can *act* on.

    Retargeting a done task reopens it, and the specification says the product
    must say so before it happens. That is only buildable if the endpoint's
    refusal is distinguishable from a validation failure — a surface that can
    tell them apart can offer *"reopen it anyway"*, while one that cannot has
    only "invalid" to show.
    """

    async def test_an_unacknowledged_reopen_answers_409_with_its_own_code(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(later_id)
        )

        assert response.status_code == 409
        error = _error(response.json())
        assert error["code"] == "TASK_REOPEN_NOT_ACKNOWLEDGED"
        assert "acknowledge" in str(error["detail"]).lower()

    async def test_the_refusal_writes_nothing_at_all(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Not the status, not the anchor, and not the automatic link.

        A refusal that had already written the link would leave a trail through
        a journal the task never moved to.
        """
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(later_id)
        )

        assert response.status_code == 409
        assert await stored_status(async_connection, task_id) == "done"
        assert await stored_anchors(async_connection, task_id) == (creating_id, due_id)
        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    async def test_the_same_request_acknowledged_reopens_the_task(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The refusal names a way through, and the way through works."""
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget",
            json=_retarget_body(later_id, acknowledge_reopen=True),
        )

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["status"] == "not_done"
        assert await stored_status(async_connection, task_id) == "not_done"

    async def test_a_cancelled_task_is_reopened_without_any_acknowledgement(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Retargeting is the documented — and only — way out of *cancelled*.

        It is what ``TASK_STATUS_TRANSITION_REFUSED`` tells a caller to do, so
        gating it would be asking the user to confirm the remedy they were just
        sent to.
        """
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.CANCELLED,
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(later_id)
        )

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["status"] == "not_done"

    async def test_the_acknowledgement_does_not_excuse_a_past_journal(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The gate is a confirmation, not a bypass, and it is checked last.

        A caller who has confirmed a reopen still has to have named a journal
        that satisfies invariant 4 — and one who has *not* confirmed is told
        about the journal first, rather than being asked to confirm a request
        that was never going to succeed.
        """
        creating_id, due_id = task_anchors
        past_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(past_id)
        )

        assert response.status_code == 400
        assert _error(response.json())["code"] == "TASK_DUE_JOURNAL_NOT_FUTURE"
        assert await stored_status(async_connection, task_id) == "done"


@pytest.mark.integration
class TestTheRetargetRevalidatesTheJournalRules:
    """Invariant 4 and ownership, re-run at the surface for every status."""

    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_a_past_dated_journal_is_refused_whatever_the_status(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        status: TaskStatus,
    ):
        """A due journal is being *set*, so the rule applies exactly as on creation."""
        creating_id, due_id = task_anchors
        past_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget",
            json=_retarget_body(past_id, acknowledge_reopen=True),
        )

        assert response.status_code == 400
        error = _error(response.json())
        assert error["code"] == "TASK_DUE_JOURNAL_NOT_FUTURE"
        assert "not after today" in str(error["detail"])
        assert await stored_anchors(async_connection, task_id) == (creating_id, due_id)
        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    async def test_another_users_journal_reads_as_an_absent_one(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Byte-identical once the ids are stripped, as creation's is.

        A distinguishable answer would turn the retarget into a way to probe for
        another user's journals.
        """
        creating_id, due_id = task_anchors
        foreign_id = await create_journal(
            journal_repository,
            title="Somebody else's trip",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        foreign = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(foreign_id)
        )
        absent = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(999_999)
        )

        assert foreign.status_code == absent.status_code == 404
        foreign_error, absent_error = _error(foreign.json()), _error(absent.json())
        assert (
            foreign_error["code"]
            == absent_error["code"]
            == "TASK_ANCHOR_JOURNAL_NOT_FOUND"
        )
        assert str(foreign_error["detail"]).replace(str(foreign_id), "X") == str(
            absent_error["detail"]
        ).replace("999999", "X")
        assert await stored_anchors(async_connection, task_id) == (creating_id, due_id)

    async def test_another_users_task_is_indistinguishable_from_an_absent_one(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """And is left exactly where it was."""
        _, due_id = task_anchors
        foreign_journal = await create_journal(
            journal_repository,
            title="Somebody else's day",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )
        foreign_task = await create_task(
            async_connection,
            creating_journal_id=foreign_journal,
            due_journal_id=foreign_journal,
            user_id=OTHER_USER_ID,
        )

        foreign = await authenticated_client.post(
            f"/api/tasks/{foreign_task}/retarget", json=_retarget_body(due_id)
        )
        absent = await authenticated_client.post(
            "/api/tasks/999999/retarget", json=_retarget_body(due_id)
        )

        assert foreign.status_code == absent.status_code == 404
        foreign_error, absent_error = _error(foreign.json()), _error(absent.json())
        assert foreign_error["code"] == absent_error["code"] == "TASK_NOT_FOUND"
        assert str(foreign_error["detail"]).replace(str(foreign_task), "X") == str(
            absent_error["detail"]
        ).replace("999999", "X")
        assert await stored_anchors(async_connection, foreign_task) == (
            foreign_journal,
            foreign_journal,
        )


@pytest.mark.integration
class TestRejectedRetargetBodies:
    """What a client may not send, and that the task does not move when it does."""

    @pytest.mark.parametrize(
        "body",
        [
            {"data": {"type": "task-retarget", "attributes": {}}},
            {
                "data": {
                    "type": "tasks",
                    "attributes": {"due_journal_id": 1},
                }
            },
            {
                "data": {
                    "type": "task-retarget",
                    "attributes": {"due_journal_id": 1, "status": "done"},
                }
            },
            {
                "data": {
                    "type": "task-retarget",
                    "attributes": {"due_journal_id": 1, "creating_journal_id": 1},
                }
            },
            {
                "data": {
                    "type": "task-retarget",
                    "attributes": {
                        "due_journal_id": 1,
                        "now": "2020-01-01T00:00:00+00:00",
                    },
                }
            },
            {
                "data": {
                    "type": "task-retarget",
                    "attributes": {"due_journal_id": 1, "due_date": "2026-09-01"},
                }
            },
            {
                "data": {
                    "type": "task-retarget",
                    "attributes": {"due_journal_id": 1},
                },
                "acknowledge_reopen": True,
            },
            {
                "data": {
                    "type": "task-retarget",
                    "attributes": {"due_journal_id": 1},
                    "acknowledge_reopen": True,
                }
            },
        ],
        ids=[
            "no due journal",
            "wrong resource type",
            "a status",
            "the creating journal",
            "now",
            "a bare date",
            "acknowledgement at the root",
            "acknowledgement beside the attributes",
        ],
    )
    async def test_a_rejected_body_leaves_the_task_where_it_was(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        body: dict[str, object],
    ):
        """The three nesting levels are guarded, and so is the operation's scope.

        A misspelled acknowledgement silently dropped would be worse than one
        refused: the caller would believe it had confirmed a reopen it had not.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=body
        )

        assert response.status_code == 400
        assert await stored_anchors(async_connection, task_id) == (creating_id, due_id)

    @pytest.mark.parametrize("value", ["true", "yes", 1, "1"], ids=str)
    async def test_a_truthy_non_boolean_acknowledgement_does_not_reopen_a_done_task(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        value: object,
    ):
        """The wrong *type* must not be able to confirm a reopen.

        Pydantic's ordinary ``bool`` parsing accepts all of these, so before the
        pull request's review caught it a client sending ``"true"`` reopened a
        completed task without ever sending a boolean. Asserted at the surface
        as well as on the schema, because what matters is that the task is still
        *done* afterwards — the acknowledgement gate's whole purpose.
        """
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget",
            json=_retarget_body(later_id, acknowledge_reopen=value),
        )

        assert response.status_code == 400
        assert await stored_status(async_connection, task_id) == "done"
        assert await stored_anchors(async_connection, task_id) == (creating_id, due_id)

    async def test_a_due_journal_id_beyond_int32_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """400 rather than the 500 an unbounded id used to reach the driver as."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(2_147_483_648)
        )

        assert response.status_code == 400
        assert await stored_anchors(async_connection, task_id) == (creating_id, due_id)

    async def test_a_path_task_id_beyond_int32_is_rejected(
        self,
        authenticated_client: AsyncClient,
        task_anchors: tuple[int, int],
    ):
        _, due_id = task_anchors

        response = await authenticated_client.post(
            "/api/tasks/2147483648/retarget", json=_retarget_body(due_id)
        )

        assert response.status_code == 400


@pytest.mark.integration
class TestEveryTaskResponseCarriesTheSameAttributes:
    """One resource type, one attribute set, whichever route produced it.

    A ``tasks`` resource whose fields varied by route would be a worse contract
    than the one extra indexed read it saves: a client could not write a single
    renderer for it, and a ``PATCH`` answering with an empty trail for a task
    that has one would simply be wrong.
    """

    async def test_a_freshly_created_task_has_an_empty_trail(
        self,
        authenticated_client: AsyncClient,
        task_anchors: tuple[int, int],
    ):
        """Creation writes no intermediate link, and says so rather than omitting it."""
        creating_id, due_id = task_anchors

        response = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(text="print the permit", due_journal_id=due_id),
        )

        assert response.status_code == 201
        assert response.json()["data"]["attributes"]["intermediate_journal_ids"] == []

    async def test_a_status_change_reports_the_trail_the_task_already_had(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Answering ``[]`` here would be a lie rather than an omission."""
        creating_id, due_id = task_anchors
        passed_id = await create_journal(
            journal_repository, title="Where it used to be due", days_offset=-7
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=passed_id
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}", json=_update_body(task_id, status="done")
        )

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["intermediate_journal_ids"] == [
            passed_id
        ]


def _link_body(contact_id: int, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {"type": "contacts", "id": str(contact_id)}
    data.update(overrides)
    return {"data": data}


@pytest.mark.integration
class TestContactLinkEndpoints:
    """``POST``/``DELETE`` under ``/api/tasks/{id}/relationships/contacts``.

    Both answer **204**. There is no read model yet — no endpoint returns a
    task's contacts — so echoing the link back would be a second definition of
    what got linked, sitting beside a read surface that does not exist. 204 is
    also what makes idempotency invisible to the client, which is the point of
    it: a repeat of either call is indistinguishable from the first.
    """

    async def test_linking_a_contact_writes_the_row(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(async_connection, first_name="Sarah")

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/contacts", json=_link_body(sarah)
        )

        assert response.status_code == 204
        assert await linked_contact_ids(async_connection, task_id) == [sarah]

    async def test_linking_the_same_contact_again_answers_the_same_way(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A retry is not an error, and does not produce a second row."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(async_connection, first_name="Sarah")
        path = f"/api/tasks/{task_id}/relationships/contacts"

        first = await authenticated_client.post(path, json=_link_body(sarah))
        second = await authenticated_client.post(path, json=_link_body(sarah))

        assert (first.status_code, second.status_code) == (204, 204)
        assert (
            await count(
                async_connection, COUNT_CONTACT_LINKS_FOR_TASK, {"task_id": task_id}
            )
            == 1
        )

    async def test_unlinking_a_contact_removes_the_row(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(async_connection, first_name="Sarah")
        await link_contact(async_connection, task_id=task_id, contact_id=sarah)

        response = await authenticated_client.delete(
            f"/api/tasks/{task_id}/relationships/contacts/{sarah}"
        )

        assert response.status_code == 204
        assert await linked_contact_ids(async_connection, task_id) == []

    async def test_unlinking_again_answers_the_same_way(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """``DELETE`` is idempotent, so a second one is still a 204."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(async_connection, first_name="Sarah")
        await link_contact(async_connection, task_id=task_id, contact_id=sarah)
        path = f"/api/tasks/{task_id}/relationships/contacts/{sarah}"

        first = await authenticated_client.delete(path)
        second = await authenticated_client.delete(path)

        assert (first.status_code, second.status_code) == (204, 204)

    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_links_are_editable_in_every_status(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        status: TaskStatus,
    ):
        """Including *cancelled*, which ``PATCH`` refuses to leave."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )
        sarah = await create_contact(async_connection, first_name="Sarah")

        linked = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/contacts", json=_link_body(sarah)
        )
        unlinked = await authenticated_client.delete(
            f"/api/tasks/{task_id}/relationships/contacts/{sarah}"
        )

        assert (linked.status_code, unlinked.status_code) == (204, 204)
        assert await stored_status(async_connection, task_id) == status.value

    async def test_deleting_the_contact_afterwards_leaves_the_task_alone(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Criterion 4 through the surface that made the link."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(async_connection, first_name="Sarah")
        await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/contacts", json=_link_body(sarah)
        )

        await delete_contact(async_connection, sarah)

        assert await linked_contact_ids(async_connection, task_id) == []
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 1
        assert await stored_status(async_connection, task_id) == "not_done"


@pytest.mark.integration
class TestContactLinkRejections:
    """One test per way the endpoint says no."""

    async def test_an_unknown_contact_answers_404_and_writes_nothing(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/contacts", json=_link_body(999_999)
        )

        assert response.status_code == 404
        assert _error(response.json())["code"] == "CONTACT_NOT_FOUND"
        assert await linked_contact_ids(async_connection, task_id) == []

    async def test_another_users_task_is_indistinguishable_from_an_absent_one(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Neither the status nor the message may say which of the two it was."""
        foreign_journal = await create_journal(
            journal_repository,
            title="Somebody else's day",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )
        foreign_task = await create_task(
            async_connection,
            creating_journal_id=foreign_journal,
            due_journal_id=foreign_journal,
            user_id=OTHER_USER_ID,
        )
        sarah = await create_contact(async_connection, first_name="Sarah")

        foreign = await authenticated_client.post(
            f"/api/tasks/{foreign_task}/relationships/contacts", json=_link_body(sarah)
        )
        absent = await authenticated_client.post(
            "/api/tasks/999999/relationships/contacts", json=_link_body(sarah)
        )

        assert foreign.status_code == absent.status_code == 404
        foreign_detail = str(_error(foreign.json())["detail"])
        absent_detail = str(_error(absent.json())["detail"])
        assert foreign_detail.replace(str(foreign_task), "X") == absent_detail.replace(
            "999999", "X"
        )
        assert await linked_contact_ids(async_connection, foreign_task) == []

    async def test_unlinking_another_users_task_leaves_its_link_in_place(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        foreign_journal = await create_journal(
            journal_repository,
            title="Somebody else's day",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )
        foreign_task = await create_task(
            async_connection,
            creating_journal_id=foreign_journal,
            due_journal_id=foreign_journal,
            user_id=OTHER_USER_ID,
        )
        sarah = await create_contact(async_connection, first_name="Sarah")
        await link_contact(async_connection, task_id=foreign_task, contact_id=sarah)

        response = await authenticated_client.delete(
            f"/api/tasks/{foreign_task}/relationships/contacts/{sarah}"
        )

        assert response.status_code == 404
        assert await linked_contact_ids(async_connection, foreign_task) == [sarah]

    @pytest.mark.parametrize("field", ["relationship_type", "role", "status"])
    async def test_a_body_carrying_relationship_data_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        field: str,
    ):
        """A task-contact link is a plain reference and says so by refusing.

        Dropping the field silently would leave a client believing it had
        recorded a role that nothing stored.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(async_connection, first_name="Sarah")

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/contacts",
            json=_link_body(sarah, **{field: "PARTICIPANT"}),
        )

        assert response.status_code == 400
        assert await linked_contact_ids(async_connection, task_id) == []

    async def test_a_body_declaring_another_resource_type_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(async_connection, first_name="Sarah")

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/contacts",
            json={"data": {"type": "tasks", "id": str(sarah)}},
        )

        assert response.status_code == 400
        assert await linked_contact_ids(async_connection, task_id) == []

    async def test_a_body_with_no_contact_id_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/contacts",
            json={"data": {"type": "contacts"}},
        )

        assert response.status_code == 400

    async def test_unknown_members_beside_the_data_member_are_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The envelope level Phase 5's review found open on the create request."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(async_connection, first_name="Sarah")

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/contacts",
            json={
                "data": {"type": "contacts", "id": str(sarah)},
                "relationship_type": "MENTION",
            },
        )

        assert response.status_code == 400
        assert await linked_contact_ids(async_connection, task_id) == []


@pytest.mark.integration
class TestIdsOutsideTheColumnsRange:
    """An id no row could have is a client error, not a server one.

    Python's ``int`` is unbounded and every id column here is a PostgreSQL
    ``INTEGER``, so ``2147483648`` used to parse cleanly, reach the repository
    and die in the driver — asyncpg refuses to *bind* an out-of-range value, so
    the caller got a 500 for what is plainly a bad request. Found by the pull
    request's automated review, and reproduced on five routes before it was
    fixed, including two this phase did not add.

    The bound belongs at the surface because it is a fact about the column's
    width rather than a domain rule: no service could enforce it without first
    doing the query that fails.
    """

    async def test_a_body_contact_id_beyond_int32_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/contacts",
            json=_link_body(2_147_483_648),
        )

        assert response.status_code == 400
        assert await linked_contact_ids(async_connection, task_id) == []

    async def test_a_path_task_id_beyond_int32_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
    ):
        sarah = await create_contact(async_connection, first_name="Sarah")

        response = await authenticated_client.post(
            "/api/tasks/2147483648/relationships/contacts", json=_link_body(sarah)
        )

        assert response.status_code == 400

    async def test_a_path_contact_id_beyond_int32_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.delete(
            f"/api/tasks/{task_id}/relationships/contacts/2147483648"
        )

        assert response.status_code == 400

    async def test_a_zero_id_is_rejected_rather_than_reported_as_missing(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Serial columns start at 1, so zero identifies nothing.

        Answering 404 would suggest the row might have existed once; the id is
        simply not one this system can ever issue.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/contacts", json=_link_body(0)
        )

        assert response.status_code == 400

    async def test_the_status_route_is_bounded_too(
        self,
        authenticated_client: AsyncClient,
    ):
        """A route this phase did not add, fixed with it.

        Leaving `PATCH` broken beside a fixed neighbour in the same module would
        be a worse outcome than either fixing both or fixing neither.
        """
        response = await authenticated_client.patch(
            "/api/tasks/2147483648",
            json=_update_body(2_147_483_648, status="done"),
        )

        assert response.status_code == 400

    async def test_create_rejects_a_contact_id_beyond_int32(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The same, on the create path's contact list."""
        creating_id, due_id = task_anchors

        response = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(
                text="print the permit",
                due_journal_id=due_id,
                contact_ids=[2_147_483_648],
            ),
        )

        assert response.status_code == 400
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0


@pytest.mark.integration
class TestTheEndpointRecordsUiProvenance:
    """A change made here has to be identifiable as one the *user* made.

    The service defaults to ``SYSTEM``, so an endpoint that simply forgot to say
    where it was calling from would still work, still write its row, and still
    publish its event — and every change a person made in the browser would be
    filed under "system" in their own history. Nothing above the outbox row can
    catch that, which is why it is asserted here rather than left to the service
    tests: a shared service is no evidence that its callers reach it correctly.
    """

    async def test_a_created_task_is_attributed_to_the_ui(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors

        response = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(text="print the permit", due_journal_id=due_id),
        )
        assert response.status_code == 201

        (event,) = await task_events(async_connection)
        assert event.event_type == "TaskCreated"
        assert event.payload["source"] == Provenance.UI.value
        assert event.payload["changed_by"] == "ui"

    async def test_a_deleted_task_is_attributed_to_the_ui(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        creating_id = await create_journal(journal_repository, title="Where it arose")
        due_id = await create_journal(
            journal_repository, title="Where it matters", days_offset=7
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        response = await authenticated_client.delete(f"/api/tasks/{task_id}")
        assert response.status_code == 204

        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskDeleted"
        assert event.payload["source"] == Provenance.UI.value
        assert event.payload["changed_by"] == "ui"

    async def test_a_reworded_task_is_attributed_to_the_ui(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print the permit",
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}",
            json=_update_body(task_id, text="print the permit and the map"),
        )
        assert response.status_code == 200

        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskUpdated"
        assert event.payload["source"] == Provenance.UI.value
        assert event.payload["changed_by"] == "ui"

    async def test_a_status_change_is_attributed_to_the_ui(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The same endpoint, the other field — and the same threading.

        Both halves are asserted because the endpoint passes provenance once,
        for the whole call: a test that only ever reworded would keep passing if
        the status path grew its own service call that forgot to.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}",
            json=_update_body(task_id, status=TaskStatus.DONE.value),
        )
        assert response.status_code == 200

        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskUpdated"
        assert event.payload["changed_fields"] == {"status": ["not_done", "done"]}
        assert event.payload["source"] == Provenance.UI.value
        assert event.payload["changed_by"] == "ui"

    async def test_rewording_and_completing_in_one_request_records_one_change(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """One ``PATCH`` is one change, through the surface a person uses.

        JSON:API says a request is one change and the service publishes one
        event for it; this asserts that end to end, so a future split into
        per-field events would have to change a test written from the user's
        side rather than only a service one.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print the permit",
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}",
            json=_update_body(
                task_id,
                text="print the permit and the map",
                status=TaskStatus.DONE.value,
            ),
        )
        assert response.status_code == 200

        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.payload["changed_fields"] == {
            "text": ["print the permit", "print the permit and the map"],
            "status": ["not_done", "done"],
        }

    async def test_a_retarget_is_attributed_to_the_ui(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The endpoint's own hop, which no service test can stand in for.

        This one crosses an extra wrapper — ``retarget_due_journal_with_trail``
        — before it reaches the write that publishes, and the wrapper is the
        ideal place to lose provenance: the task still moves, an event is still
        written, and the only symptom is the user's own deferral being filed
        under "system".
        """
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(later_id)
        )
        assert response.status_code == 200

        link, event = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskDueJournalRetargeted"
        assert event.payload["changed_fields"] == {"due_journal_id": [due_id, later_id]}
        assert event.payload["source"] == Provenance.UI.value
        assert event.payload["changed_by"] == "ui"
        # The journal the retarget retained, announced separately and attributed
        # to the same person: one action, two rows, one actor.
        assert link.event_type == "TaskJournalLinked"
        assert link.payload["journal_id"] == due_id
        assert link.payload["origin"] == "retarget"
        assert link.payload["source"] == Provenance.UI.value
        assert link.payload["changed_by"] == "ui"

    async def test_reopening_a_done_task_records_the_reopen_as_the_users(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The status change reaches the stream, attributed to the person.

        Reopening a completion is the case the UI has to confirm before it
        happens, so it is also the case where "who did this?" matters most in
        the history that follows.
        """
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget",
            json=_retarget_body(later_id, acknowledge_reopen=True),
        )
        assert response.status_code == 200

        _, event = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskDueJournalRetargeted"
        assert event.payload["changed_fields"]["status"] == ["done", "not_done"]
        assert event.payload["source"] == Provenance.UI.value
        assert event.payload["changed_by"] == "ui"

    async def test_attaching_a_journal_is_attributed_to_the_ui(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """A link a person asked for, recorded as theirs and as ``manual``.

        ``origin`` is what separates this row from the one a retarget derives,
        and both reach the outbox through the same event type — so the endpoint
        has to be asserted on both keys or a link filed under the wrong cause
        would still look correct.
        """
        creating_id, due_id = task_anchors
        mentioned_id = await create_journal(
            journal_repository, title="Where it came up again", days_offset=3
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/intermediate-journals",
            json=_journal_link_body(mentioned_id),
        )
        assert response.status_code == 204

        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskJournalLinked"
        assert event.payload["journal_id"] == mentioned_id
        assert event.payload["origin"] == "manual"
        assert event.payload["source"] == Provenance.UI.value
        assert event.payload["changed_by"] == "ui"

    async def test_detaching_a_journal_is_attributed_to_the_ui(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        mentioned_id = await create_journal(
            journal_repository, title="Where it came up again", days_offset=3
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )
        attached = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/intermediate-journals",
            json=_journal_link_body(mentioned_id),
        )
        assert attached.status_code == 204

        response = await authenticated_client.delete(
            f"/api/tasks/{task_id}/relationships/intermediate-journals/{mentioned_id}"
        )
        assert response.status_code == 204

        _, event = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskJournalUnlinked"
        assert event.payload["journal_id"] == mentioned_id
        assert event.payload["source"] == Provenance.UI.value
        assert event.payload["changed_by"] == "ui"

    async def test_linking_a_contact_is_attributed_to_the_ui(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A person added to a task, recorded as the *user's* doing.

        Contact membership travels as a ``TaskUpdated`` carrying
        ``changed_fields`` rather than a type of its own, so the key is asserted
        alongside the provenance: an endpoint reaching the wrong service method
        would publish a ``TaskUpdated`` too, and a test checking only the type
        and the source would wave that through.
        """
        creating_id, due_id = task_anchors
        sarah = await create_contact(async_connection, first_name="Sarah")
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/contacts", json=_link_body(sarah)
        )
        assert response.status_code == 204

        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskUpdated"
        assert event.payload["changed_fields"] == {
            contact_field_name(sarah): [None, sarah]
        }
        assert event.payload["source"] == Provenance.UI.value
        assert event.payload["changed_by"] == "ui"

    async def test_unlinking_a_contact_is_attributed_to_the_ui(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The ``DELETE`` threads provenance too, which the ``POST`` cannot show.

        Asserted separately rather than assumed from the link above: the two are
        different endpoint functions calling different service methods, and each
        would keep working — silently filing a person's own change under
        "system" — if it forgot.
        """
        creating_id, due_id = task_anchors
        sarah = await create_contact(async_connection, first_name="Sarah")
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )
        linked = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/contacts", json=_link_body(sarah)
        )
        assert linked.status_code == 204

        response = await authenticated_client.delete(
            f"/api/tasks/{task_id}/relationships/contacts/{sarah}"
        )
        assert response.status_code == 204

        _, event = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskUpdated"
        assert event.payload["changed_fields"] == {
            contact_field_name(sarah): [sarah, None]
        }
        assert event.payload["source"] == Provenance.UI.value
        assert event.payload["changed_by"] == "ui"

    async def test_a_patch_that_changes_nothing_records_nothing(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Resending the current values is what a form submit routinely does."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print the permit",
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}",
            json=_update_body(
                task_id, text="print the permit", status=TaskStatus.NOT_DONE.value
            ),
        )
        assert response.status_code == 200

        assert await task_events(async_connection, task_id=task_id) == []

    async def test_a_refused_delete_records_nothing(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Another user's task 404s, and must not leave a deletion in the record."""
        creating_id = await create_journal(
            journal_repository, title="Theirs", user_id=OTHER_USER_ID
        )
        due_id = await create_journal(
            journal_repository,
            title="Theirs, later",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )
        foreign_task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            user_id=OTHER_USER_ID,
        )

        response = await authenticated_client.delete(f"/api/tasks/{foreign_task_id}")

        assert response.status_code == 404
        assert await task_events(async_connection) == []


def _journal_link_body(journal_id: int, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {"type": "journals", "id": str(journal_id)}
    data.update(overrides)
    return {"data": data}


@pytest.mark.integration
class TestIntermediateJournalLinkEndpoints:
    """``POST``/``DELETE`` under ``/api/tasks/{id}/relationships/intermediate-journals``.

    The relationship is named for the role it holds, not for the resource it
    points at. A task has three journal relationships — creating, due and
    intermediate — and this route manipulates exactly one of them; calling it
    ``/journals`` would promise a route that can set an anchor, which the service
    refuses. The body's resource ``type`` is still ``journals``, because that is
    what the identifier points at.

    Both verbs answer **204**, for the reasons the contact routes do: there is no
    read model to echo, and a 204 is what keeps an idempotent operation
    indistinguishable from its own repeat.
    """

    async def test_attaching_a_journal_writes_the_row(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/intermediate-journals",
            json=_journal_link_body(mentioned),
        )

        assert response.status_code == 204
        assert await intermediate_journal_ids(async_connection, task_id) == [mentioned]

    async def test_attaching_again_answers_the_same_and_leaves_one_row(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Idempotency is invisible to the client, which is the whole of it."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")
        path = f"/api/tasks/{task_id}/relationships/intermediate-journals"

        first = await authenticated_client.post(
            path, json=_journal_link_body(mentioned)
        )
        second = await authenticated_client.post(
            path, json=_journal_link_body(mentioned)
        )

        assert (first.status_code, second.status_code) == (204, 204)
        assert await intermediate_journal_ids(async_connection, task_id) == [mentioned]

    async def test_detaching_a_journal_removes_the_row(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mentioned
        )

        response = await authenticated_client.delete(
            f"/api/tasks/{task_id}/relationships/intermediate-journals/{mentioned}"
        )

        assert response.status_code == 204
        assert await intermediate_journal_ids(async_connection, task_id) == []

    async def test_detaching_again_answers_the_same(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mentioned
        )
        path = f"/api/tasks/{task_id}/relationships/intermediate-journals/{mentioned}"

        first = await authenticated_client.delete(path)
        second = await authenticated_client.delete(path)

        assert (first.status_code, second.status_code) == (204, 204)

    async def test_detaching_a_deleted_journal_is_accepted(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The tidy-up call must not 404 on the journal the user just removed."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mentioned
        )
        await delete_journal(async_connection, mentioned)

        response = await authenticated_client.delete(
            f"/api/tasks/{task_id}/relationships/intermediate-journals/{mentioned}"
        )

        assert response.status_code == 204

    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_attaching_works_in_any_status(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        status: TaskStatus,
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )
        mentioned = await create_journal(journal_repository, title="Came up again")

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/intermediate-journals",
            json=_journal_link_body(mentioned),
        )

        assert response.status_code == 204
        assert await intermediate_journal_ids(async_connection, task_id) == [mentioned]
        assert await stored_status(async_connection, task_id) == status.value


@pytest.mark.integration
class TestIntermediateJournalLinkRejections:
    """Every refusal, at the surface a client actually reaches.

    A shared service is no evidence that both callers reach it — the lesson
    Phase 5 recorded after finding every task rejection arriving at AI clients as
    "internal error" — so the whole matrix is asserted again here, with the
    JSON:API ``code`` each answer carries.
    """

    @pytest.mark.parametrize("anchor", ["creating", "due"])
    async def test_attaching_an_anchor_journal_is_a_409(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        anchor: str,
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        journal_id = creating_id if anchor == "creating" else due_id

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/intermediate-journals",
            json=_journal_link_body(journal_id),
        )

        assert response.status_code == 409
        assert _error(response.json())["code"] == "TASK_JOURNAL_IS_ANCHOR"
        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    @pytest.mark.parametrize("anchor", ["creating", "due"])
    async def test_detaching_an_anchor_journal_is_a_409(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        anchor: str,
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        journal_id = creating_id if anchor == "creating" else due_id

        response = await authenticated_client.delete(
            f"/api/tasks/{task_id}/relationships/intermediate-journals/{journal_id}"
        )

        assert response.status_code == 409
        assert _error(response.json())["code"] == "TASK_JOURNAL_IS_ANCHOR"

    async def test_an_unknown_journal_is_a_404_naming_the_journal(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The journal domain's answer, not a task-shaped one.

        ``JOURNAL_NOT_FOUND`` tells the client which resource it got wrong;
        ``TASK_ANCHOR_JOURNAL_NOT_FOUND`` would describe a rule about anchors
        that this call is not about.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/intermediate-journals",
            json=_journal_link_body(999_999),
        )

        assert response.status_code == 404
        assert _error(response.json())["code"] == "JOURNAL_NOT_FOUND"
        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    async def test_another_users_journal_reads_as_an_absent_one(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Identical once the id is normalised, so this is not a probe.

        Deliberately **not** described as byte-identical: each body embeds the id
        the caller supplied, so the two differ exactly there and nowhere else.
        Phase 6's entry hedges the same claim the same way; this phase's first
        draft dropped the hedge and review caught it.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        theirs = await create_journal(
            journal_repository, title="Not yours", user_id=OTHER_USER_ID
        )
        path = f"/api/tasks/{task_id}/relationships/intermediate-journals"

        foreign = await authenticated_client.post(path, json=_journal_link_body(theirs))
        absent = await authenticated_client.post(path, json=_journal_link_body(999_999))

        assert foreign.status_code == absent.status_code == 404
        # The same template either way, differing only in the id the caller
        # supplied — which is what makes the two answers indistinguishable as
        # evidence about whose journal it was.
        assert _error(foreign.json())["detail"] == str(JournalNotFoundError(theirs))
        assert _error(absent.json())["detail"] == str(JournalNotFoundError(999_999))
        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    async def test_another_users_task_answers_exactly_as_an_absent_one(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """On both verbs, and their link survives."""
        their_journal = await create_journal(
            journal_repository, title="Theirs", user_id=OTHER_USER_ID
        )
        their_task = await create_task(
            async_connection,
            creating_journal_id=their_journal,
            due_journal_id=their_journal,
            user_id=OTHER_USER_ID,
        )
        their_mention = await create_journal(
            journal_repository, title="Their mention", user_id=OTHER_USER_ID
        )
        await link_intermediate_journal(
            async_connection, task_id=their_task, journal_id=their_mention
        )
        mine = await create_journal(journal_repository, title="Mine")

        foreign_attach = await authenticated_client.post(
            f"/api/tasks/{their_task}/relationships/intermediate-journals",
            json=_journal_link_body(mine),
        )
        absent_attach = await authenticated_client.post(
            "/api/tasks/999999/relationships/intermediate-journals",
            json=_journal_link_body(mine),
        )
        foreign_detach = await authenticated_client.delete(
            f"/api/tasks/{their_task}/relationships/intermediate-journals/"
            f"{their_mention}"
        )
        absent_detach = await authenticated_client.delete(
            f"/api/tasks/999999/relationships/intermediate-journals/{their_mention}"
        )

        # The two answers compared *with each other*, which is what the name
        # promises — an earlier version checked each against a constant and would
        # have passed for two bodies that differed in any other way. The id the
        # caller supplied is the only legitimate difference, so it is normalised
        # out; a foreign task must otherwise be indistinguishable from an absent
        # one, or the endpoint becomes a way to probe for other users' tasks.
        assert foreign_attach.status_code == absent_attach.status_code == 404
        assert _error(foreign_attach.json())["code"] == "TASK_NOT_FOUND"
        assert str(_error(foreign_attach.json())["detail"]).replace(
            str(their_task), "X"
        ) == str(_error(absent_attach.json())["detail"]).replace("999999", "X")

        # And the same on DELETE, which the earlier version never issued for the
        # absent case at all.
        assert foreign_detach.status_code == absent_detach.status_code == 404
        assert str(_error(foreign_detach.json())["detail"]).replace(
            str(their_task), "X"
        ) == str(_error(absent_detach.json())["detail"]).replace("999999", "X")

        assert await intermediate_journal_ids(async_connection, their_task) == [
            their_mention
        ]

    @pytest.mark.parametrize("field", ["role", "relationship_type", "status"])
    async def test_a_role_field_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        field: str,
    ):
        """An intermediate link is a mention; a field it does not have is refused."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/intermediate-journals",
            json=_journal_link_body(mentioned, **{field: "due"}),
        )

        assert response.status_code == 400
        assert await intermediate_journal_ids(async_connection, task_id) == []

    async def test_another_resource_type_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The two link routes take structurally identical bodies but for the type."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/intermediate-journals",
            json=_journal_link_body(mentioned, type="contacts"),
        )

        assert response.status_code == 400
        assert await intermediate_journal_ids(async_connection, task_id) == []

    async def test_unknown_members_beside_the_data_member_are_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/intermediate-journals",
            json={"data": {"type": "journals", "id": str(mentioned)}, "role": "due"},
        )

        assert response.status_code == 400
        assert await intermediate_journal_ids(async_connection, task_id) == []

    async def test_a_body_journal_id_beyond_int32_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The 500 issue #1272 is about, closed on this phase's routes too."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/intermediate-journals",
            json=_journal_link_body(2_147_483_648),
        )

        assert response.status_code == 400
        assert await intermediate_journal_ids(async_connection, task_id) == []

    async def test_a_path_journal_id_beyond_int32_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.delete(
            f"/api/tasks/{task_id}/relationships/intermediate-journals/2147483648"
        )

        assert response.status_code == 400

    async def test_a_non_integer_body_id_is_rejected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/relationships/intermediate-journals",
            json={"data": {"type": "journals", "id": "not-a-number"}},
        )

        assert response.status_code == 400


@pytest.mark.integration
class TestEveryTaskRouteEmitsOneResourceShape:
    """The `self` link on the routes that *write* a task, not only the read.

    The read arriving is what made the link emittable at all, but the claim the
    change makes is that **every** route returning a task emits the same shape —
    so a regression that dropped ``base_url`` (or the link) from ``_to_resource``
    while the read stayed green is exactly what this exists to catch. Asserted
    on the shape rather than the exact string: the base URL is the test client's,
    not something this file should hard-code.
    """

    async def test_create_patch_and_retarget_all_carry_an_absolute_self_link(
        self,
        authenticated_client: AsyncClient,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """One task, driven through all three write routes."""
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="Later still", days_offset=21
        )

        created = await authenticated_client.post(
            f"/api/journals/{creating_id}/tasks",
            json=_body(text="print the permit", due_journal_id=due_id),
        )
        task_id = int(created.json()["data"]["id"])
        patched = await authenticated_client.patch(
            f"/api/tasks/{task_id}", json=_update_body(task_id, text="reworded")
        )
        retargeted = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget",
            json={
                "data": {
                    "type": "task-retarget",
                    "attributes": {"due_journal_id": later_id},
                }
            },
        )

        for response in (created, patched, retargeted):
            assert response.status_code in (200, 201)
            self_link = response.json()["data"]["links"]["self"]
            assert self_link.startswith("http")
            assert self_link.endswith(f"/api/tasks/{task_id}")


@pytest.mark.integration
class TestGetTaskEndpoint:
    """``GET /api/tasks/{task_id}`` — the first route that reads a task back.

    Every write response so far has carried the journal trail as bare ids
    because there was nowhere to resolve them. This is where a task becomes
    readable whole: journals by role with their titles and dates, contacts, and
    the lapse verdict the surfaces are asked to mark.
    """

    async def test_it_returns_the_task_with_its_journals_resolved(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Both anchors come back as objects, not as ids to look up."""
        creating_id, due_id = task_anchors
        mention_id = await create_journal(journal_repository, title="Revisited")
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print the permit",
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mention_id
        )

        response = await authenticated_client.get(f"/api/tasks/{task_id}")

        assert response.status_code == 200
        attributes = response.json()["data"]["attributes"]
        assert attributes["text"] == "print the permit"
        assert attributes["status"] == "not_done"
        assert attributes["creating_journal"]["id"] == creating_id
        assert attributes["creating_journal"]["title"] == "Where it arose"
        assert attributes["due_journal"]["id"] == due_id
        assert [ref["id"] for ref in attributes["intermediate_journals"]] == [
            mention_id
        ]

    async def test_the_scalar_attributes_match_the_write_responses(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A superset, so one renderer serves a written task and a read one."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.get(f"/api/tasks/{task_id}")

        attributes = response.json()["data"]["attributes"]
        assert attributes["creating_journal_id"] == creating_id
        assert attributes["due_journal_id"] == due_id
        assert attributes["intermediate_journal_ids"] == []
        assert response.json()["data"]["type"] == "tasks"
        assert response.json()["data"]["id"] == str(task_id)

    async def test_it_carries_a_self_link(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The link the write responses withheld until this route existed.

        Absolute, like every other ``links.self`` in this API — the base URL is
        the request's, so a client resolving ``self`` uniformly across resource
        types gets one shape rather than two.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.get(f"/api/tasks/{task_id}")

        self_link = response.json()["data"]["links"]["self"]
        assert self_link.startswith("http")
        assert self_link.endswith(f"/api/tasks/{task_id}")

    async def test_it_returns_the_linked_contacts(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Named and pictured, which is what a row showing a person needs."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        contact_id = await create_contact(async_connection, first_name="Sarah")
        await link_contact(async_connection, task_id=task_id, contact_id=contact_id)

        response = await authenticated_client.get(f"/api/tasks/{task_id}")

        (contact,) = response.json()["data"]["attributes"]["contacts"]
        assert contact["id"] == contact_id
        assert contact["display_name"] == "Sarah"

    async def test_a_task_that_has_not_lapsed_says_so(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A future due journal, so neither cause applies."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.get(f"/api/tasks/{task_id}")

        attributes = response.json()["data"]["attributes"]
        assert attributes["lapsed"] is False
        assert attributes["lapse_reason"] is None

    async def test_a_task_whose_due_journal_has_passed_is_lapsed(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The ordinary lapse, reported with its reason."""
        creating_id, _ = task_anchors
        passed_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=passed_id,
        )

        response = await authenticated_client.get(f"/api/tasks/{task_id}")

        attributes = response.json()["data"]["attributes"]
        assert attributes["lapsed"] is True
        assert attributes["lapse_reason"] == "date_passed"

    async def test_a_task_whose_due_journal_was_cancelled_says_which_cause(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """A future journal, cancelled — so only the event state lapses it.

        The distinct reason is what lets a surface say "the meeting was called
        off" rather than "the day went by", which are different news.
        """
        creating_id, _ = task_anchors
        cancelled_id = await create_journal(
            journal_repository, title="Cancelled meeting", days_offset=7
        )
        await mark_journal_as_event(
            async_connection, cancelled_id, event_state=EventState.CANCELLED
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=cancelled_id,
        )

        response = await authenticated_client.get(f"/api/tasks/{task_id}")

        attributes = response.json()["data"]["attributes"]
        assert attributes["lapse_reason"] == "due_journal_cancelled"
        assert attributes["due_journal"]["cancelled"] is True

    async def test_a_done_task_is_not_lapsed_however_old_its_journal(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """A commitment that was met cannot then be let slide."""
        creating_id, _ = task_anchors
        passed_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=passed_id,
            status=TaskStatus.DONE,
        )

        response = await authenticated_client.get(f"/api/tasks/{task_id}")

        assert response.json()["data"]["attributes"]["lapsed"] is False

    async def test_another_users_task_is_not_found(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """A real task, really owned by somebody else, answers 404."""
        theirs_journal = await create_journal(
            journal_repository, title="Theirs", user_id=OTHER_USER_ID
        )
        theirs = await create_task(
            async_connection,
            creating_journal_id=theirs_journal,
            due_journal_id=theirs_journal,
            user_id=OTHER_USER_ID,
        )

        response = await authenticated_client.get(f"/api/tasks/{theirs}")

        assert response.status_code == 404
        assert _error(response.json())["code"] == "TASK_NOT_FOUND"

    async def test_an_unknown_task_answers_the_same_way(
        self, authenticated_client: AsyncClient
    ):
        """Indistinguishable from somebody else's, so neither can be probed for.

        The two payloads differ only in the id the caller supplied, which is the
        same hedge every other task 404 on this surface carries.
        """
        response = await authenticated_client.get("/api/tasks/999999")

        assert response.status_code == 404
        assert _error(response.json())["code"] == "TASK_NOT_FOUND"

    async def test_an_id_beyond_int32_is_rejected_rather_than_hitting_the_driver(
        self, authenticated_client: AsyncClient
    ):
        """A 400 for an id no row could hold, not a 500 from parameter binding."""
        response = await authenticated_client.get("/api/tasks/2147483648")

        assert response.status_code == 400

    async def test_a_zero_id_is_rejected(self, authenticated_client: AsyncClient):
        """Serial columns start at one, so zero identifies nothing."""
        response = await authenticated_client.get("/api/tasks/0")

        assert response.status_code == 400


@pytest.mark.integration
class TestListJournalTasksEndpoint:
    """``GET /api/journals/{journal_id}/tasks`` — the journal's three groups."""

    async def test_it_groups_the_journals_tasks_by_link_role(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Due here, created here, mentioned here — the specification's words."""
        viewed_id, elsewhere_id = task_anchors
        due_here = await create_task(
            async_connection,
            creating_journal_id=elsewhere_id,
            due_journal_id=viewed_id,
        )
        created_here = await create_task(
            async_connection,
            creating_journal_id=viewed_id,
            due_journal_id=elsewhere_id,
        )
        mentioned_here = await create_task(
            async_connection,
            creating_journal_id=elsewhere_id,
            due_journal_id=elsewhere_id,
        )
        await link_intermediate_journal(
            async_connection, task_id=mentioned_here, journal_id=viewed_id
        )

        response = await authenticated_client.get(f"/api/journals/{viewed_id}/tasks")

        assert response.status_code == 200
        groups = response.json()["meta"]["groups"]
        assert groups["due"] == [due_here]
        assert groups["created"] == [created_here]
        assert groups["mentioned"] == [mentioned_here]

    async def test_a_task_in_two_roles_appears_once_in_data_naming_both(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """JSON:API forbids the same resource twice in ``data``.

        So the roles are an attribute and ``meta.groups`` carries the grouping —
        a task created in the journal it is due in is one resource holding two
        roles, not two resources.
        """
        viewed_id, _ = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=viewed_id,
            due_journal_id=viewed_id,
        )

        response = await authenticated_client.get(f"/api/journals/{viewed_id}/tasks")

        payload = response.json()
        assert [resource["id"] for resource in payload["data"]] == [str(task_id)]
        assert payload["data"][0]["attributes"]["link_roles"] == ["due", "created"]
        assert payload["meta"]["groups"]["due"] == [task_id]
        assert payload["meta"]["groups"]["created"] == [task_id]

    async def test_each_row_carries_the_full_read_attributes(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A journal's rows show text, status, contacts and the lapse marker.

        The listing is the read model entire rather than a thinner projection of
        it, which is what the specification asks each entry to show.
        """
        viewed_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=viewed_id,
            due_journal_id=due_id,
            text="return Sarah's book",
        )
        contact_id = await create_contact(async_connection, first_name="Sarah")
        await link_contact(async_connection, task_id=task_id, contact_id=contact_id)

        response = await authenticated_client.get(f"/api/journals/{viewed_id}/tasks")

        attributes = response.json()["data"][0]["attributes"]
        assert attributes["text"] == "return Sarah's book"
        assert attributes["status"] == "not_done"
        assert attributes["lapsed"] is False
        assert [contact["id"] for contact in attributes["contacts"]] == [contact_id]
        assert attributes["due_journal"]["id"] == due_id

    async def test_a_lapsed_task_stays_visible_and_marked(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """ "They remain visible on every journal they are linked to."

        The dashboard drops lapsed tasks silently; a journal must not, because
        the journal is where the user is meant to find and resurrect them.
        """
        viewed_id, _ = task_anchors
        passed_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=viewed_id,
            due_journal_id=passed_id,
        )

        response = await authenticated_client.get(f"/api/journals/{viewed_id}/tasks")

        assert response.json()["meta"]["groups"]["created"] == [task_id]
        assert response.json()["data"][0]["attributes"]["lapsed"] is True

    async def test_a_task_due_in_a_cancelled_event_journal_is_marked_on_the_row(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The cancellation cause, through the *listing* rather than the read.

        The due journal is a week out, so nothing about its date lapses the
        task — only the ``journal_calendar_info`` row, which the listing reads
        for the whole set in one statement. Worth asserting here as well as on
        ``GET /api/tasks/{id}``: the batch is a different code path to the
        single read's, and this is the row a user is meant to spot the
        cancellation on.
        """
        viewed_id, _ = task_anchors
        cancelled_id = await create_journal(
            journal_repository, title="Cancelled meeting", days_offset=7
        )
        await mark_journal_as_event(
            async_connection, cancelled_id, event_state=EventState.CANCELLED
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=viewed_id,
            due_journal_id=cancelled_id,
        )

        response = await authenticated_client.get(f"/api/journals/{viewed_id}/tasks")

        assert response.json()["meta"]["groups"]["created"] == [task_id]
        attributes = response.json()["data"][0]["attributes"]
        assert attributes["lapsed"] is True
        assert attributes["lapse_reason"] == "due_journal_cancelled"
        assert attributes["due_journal"]["cancelled"] is True

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_finished_tasks_stay_visible_too(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        status: TaskStatus,
    ):
        """A done task's link to the journal it arose in is part of the record."""
        viewed_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=viewed_id,
            due_journal_id=due_id,
            status=status,
        )

        response = await authenticated_client.get(f"/api/journals/{viewed_id}/tasks")

        assert response.json()["meta"]["groups"]["created"] == [task_id]

    async def test_the_role_filter_narrows_the_answer_without_changing_its_shape(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The other groups are empty rather than missing."""
        viewed_id, elsewhere_id = task_anchors
        due_here = await create_task(
            async_connection,
            creating_journal_id=elsewhere_id,
            due_journal_id=viewed_id,
        )
        await create_task(
            async_connection,
            creating_journal_id=viewed_id,
            due_journal_id=elsewhere_id,
        )

        response = await authenticated_client.get(
            f"/api/journals/{viewed_id}/tasks", params={"role": "due"}
        )

        payload = response.json()
        assert [resource["id"] for resource in payload["data"]] == [str(due_here)]
        assert payload["meta"]["groups"]["due"] == [due_here]
        assert payload["meta"]["groups"]["created"] == []
        assert payload["meta"]["groups"]["mentioned"] == []

    async def test_an_unknown_role_is_rejected(
        self,
        authenticated_client: AsyncClient,
        task_anchors: tuple[int, int],
    ):
        """A misspelled filter must fail rather than silently return everything.

        400 rather than FastAPI's bare 422: the application renders validation
        failures through its own JSON:API handler, so a query-parameter
        rejection reads the same as a body one.
        """
        viewed_id, _ = task_anchors

        response = await authenticated_client.get(
            f"/api/journals/{viewed_id}/tasks", params={"role": "overdue"}
        )

        assert response.status_code == 400

    async def test_a_journal_with_no_tasks_answers_empty_groups(
        self,
        authenticated_client: AsyncClient,
        task_anchors: tuple[int, int],
    ):
        """An empty journal is a normal answer, not a 404."""
        viewed_id, _ = task_anchors

        response = await authenticated_client.get(f"/api/journals/{viewed_id}/tasks")

        assert response.status_code == 200
        assert response.json()["data"] == []
        assert response.json()["meta"]["groups"] == {
            "due": [],
            "created": [],
            "mentioned": [],
        }

    async def test_another_users_journal_is_not_found(
        self,
        authenticated_client: AsyncClient,
        journal_repository: SqlJournalRepository,
    ):
        """Which is the distinction the empty answer above depends on."""
        theirs = await create_journal(
            journal_repository, title="Theirs", user_id=OTHER_USER_ID
        )

        response = await authenticated_client.get(f"/api/journals/{theirs}/tasks")

        assert response.status_code == 404
        assert _error(response.json())["code"] == "JOURNAL_NOT_FOUND"

    async def test_an_unknown_journal_answers_the_same_way(
        self, authenticated_client: AsyncClient
    ):
        """Indistinguishable, so a rejection cannot be used to probe."""
        response = await authenticated_client.get("/api/journals/999999/tasks")

        assert response.status_code == 404
        assert _error(response.json())["code"] == "JOURNAL_NOT_FOUND"

    async def test_a_journal_id_beyond_int32_is_rejected(
        self, authenticated_client: AsyncClient
    ):
        """The same bound every id on this surface carries."""
        response = await authenticated_client.get("/api/journals/2147483648/tasks")

        assert response.status_code == 400

    async def test_another_users_task_is_never_listed(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Owner scoping reaches the link tables through the task they belong to."""
        viewed_id, _ = task_anchors
        mine = await create_task(
            async_connection,
            creating_journal_id=viewed_id,
            due_journal_id=viewed_id,
        )
        theirs_journal = await create_journal(
            journal_repository, title="Theirs", user_id=OTHER_USER_ID
        )
        theirs = await create_task(
            async_connection,
            creating_journal_id=theirs_journal,
            due_journal_id=theirs_journal,
            user_id=OTHER_USER_ID,
        )
        await link_intermediate_journal(
            async_connection, task_id=theirs, journal_id=viewed_id
        )

        response = await authenticated_client.get(f"/api/journals/{viewed_id}/tasks")

        assert [resource["id"] for resource in response.json()["data"]] == [str(mine)]

    async def test_rows_are_ordered_by_due_date_then_task_id(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Soonest first, with a total tie-break, all the way to the wire."""
        viewed_id, _ = task_anchors
        far_id = await create_journal(journal_repository, title="Far", days_offset=30)
        near_id = await create_journal(journal_repository, title="Near", days_offset=2)
        far_task = await create_task(
            async_connection, creating_journal_id=viewed_id, due_journal_id=far_id
        )
        near_task = await create_task(
            async_connection, creating_journal_id=viewed_id, due_journal_id=near_id
        )

        response = await authenticated_client.get(f"/api/journals/{viewed_id}/tasks")

        assert response.json()["meta"]["groups"]["created"] == [near_task, far_task]
        assert [resource["id"] for resource in response.json()["data"]] == [
            str(near_task),
            str(far_task),
        ]


@pytest.mark.integration
class TestListUpcomingTasksEndpoint:
    """``GET /api/tasks/upcoming`` — the window the home dashboard consumes.

    The one listing on this surface that reaches across journals. Its window is
    what keeps it from becoming the "every task" collection the specification
    says no screen has, so the tests below are as interested in what it leaves
    out as in what it returns.

    Dates here are relative to the real clock rather than fixed, because ``now``
    is deliberately unreachable from a request. That is sound for a *window*
    assertion in a way it would not be for a day-boundary one: a journal seeded
    at ``now + 2 days`` is two days out at whatever instant the suite runs, and
    ``now + 7 days`` lands on the boundary day whatever the hour, since adding
    whole days preserves the wall clock.
    """

    async def test_a_task_due_inside_the_window_is_listed_whole(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The row the dashboard renders, in one response and with no follow-up.

        Text, the resolved due journal — title and date — and the linked
        contacts, which is the fourth acceptance criterion read from the
        client's side.
        """
        creating_id, _ = task_anchors
        due_id = await create_journal(
            journal_repository, title="Permit Meeting", days_offset=2
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print the permit",
        )
        contact_id = await create_contact(async_connection, first_name="Sarah")
        await link_contact(async_connection, task_id=task_id, contact_id=contact_id)

        response = await authenticated_client.get("/api/tasks/upcoming")

        assert response.status_code == 200
        (resource,) = response.json()["data"]
        assert resource["id"] == str(task_id)
        assert resource["attributes"]["text"] == "print the permit"
        assert resource["attributes"]["due_journal"]["id"] == due_id
        assert resource["attributes"]["due_journal"]["title"] == "Permit Meeting"
        assert resource["attributes"]["due_journal"]["date"] is not None
        assert [
            contact["display_name"] for contact in resource["attributes"]["contacts"]
        ] == ["Sarah"]

    async def test_the_path_resolves_to_the_listing_not_to_a_task_id(
        self, authenticated_client: AsyncClient
    ):
        """The route-ordering guard.

        ``/api/tasks/{task_id}`` would match ``upcoming`` as an id and answer
        400, so the literal route has to be declared first — the same footgun
        ``main.py`` records for ``/journals/series``. A 200 here is the whole
        assertion: it proves which route won.
        """
        response = await authenticated_client.get("/api/tasks/upcoming")

        assert response.status_code == 200
        assert "meta" in response.json()

    async def test_the_meta_names_the_window_and_the_total(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """What the dashboard's heading and show-more are rendered from."""
        creating_id, _ = task_anchors
        due_id = await create_journal(journal_repository, title="Soon", days_offset=1)
        await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        meta = (await authenticated_client.get("/api/tasks/upcoming")).json()["meta"]

        assert meta["total"] == 1
        assert meta["window"]["days_ahead"] == 7
        start = date.fromisoformat(meta["window"]["start_date"])
        end = date.fromisoformat(meta["window"]["end_date"])
        assert end - start == timedelta(days=7)

    async def test_an_explicit_days_ahead_narrows_the_window(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """A caller may look a shorter distance ahead, and the rows follow."""
        creating_id, _ = task_anchors
        near_id = await create_journal(journal_repository, title="Near", days_offset=1)
        far_id = await create_journal(journal_repository, title="Far", days_offset=5)
        near_task = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=near_id
        )
        await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=far_id
        )

        response = await authenticated_client.get("/api/tasks/upcoming?days_ahead=2")

        assert [resource["id"] for resource in response.json()["data"]] == [
            str(near_task)
        ]
        assert response.json()["meta"]["window"]["days_ahead"] == 2

    async def test_a_task_due_on_the_boundary_day_is_listed(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """ "Inclusive" reaches the wire, which is where the off-by-one shows."""
        creating_id, boundary_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=boundary_id,
        )

        response = await authenticated_client.get("/api/tasks/upcoming")

        assert [resource["id"] for resource in response.json()["data"]] == [
            str(task_id)
        ]

    async def test_a_task_beyond_the_window_is_not_listed(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """One day past the boundary is somebody else's week."""
        creating_id, _ = task_anchors
        beyond_id = await create_journal(
            journal_repository, title="Next fortnight", days_offset=8
        )
        await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=beyond_id
        )

        response = await authenticated_client.get("/api/tasks/upcoming")

        assert response.json()["data"] == []
        assert response.json()["meta"]["total"] == 0

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_a_finished_task_is_not_listed(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        status: TaskStatus,
    ):
        """The section shows what is outstanding, in either terminal status."""
        creating_id, _ = task_anchors
        due_id = await create_journal(journal_repository, title="Soon", days_offset=2)
        await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )

        response = await authenticated_client.get("/api/tasks/upcoming")

        assert response.json()["data"] == []

    async def test_a_task_whose_due_journal_was_cancelled_is_not_listed(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """**The fixture that makes the lapsed exclusion non-vacuous.**

        Not done, dated inside the window, and absent only because the meeting
        was called off. A date-passed lapse cannot fall inside a forward window,
        so without this case the exclusion could be deleted and every other test
        here would still pass.

        The same task is asserted still present on its journal in the same test:
        it is hidden from the dashboard, not lost, and "hidden here, visible
        there" is the pair the specification actually promises.
        """
        creating_id, _ = task_anchors
        due_id = await create_journal(
            journal_repository, title="Cancelled meeting", days_offset=2
        )
        await mark_journal_as_event(
            async_connection, due_id, event_state=EventState.CANCELLED
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        upcoming = await authenticated_client.get("/api/tasks/upcoming")
        on_its_journal = await authenticated_client.get(f"/api/journals/{due_id}/tasks")

        assert upcoming.json()["data"] == []
        listed = on_its_journal.json()
        assert [resource["id"] for resource in listed["data"]] == [str(task_id)]
        assert listed["data"][0]["attributes"]["lapsed"] is True
        assert (
            listed["data"][0]["attributes"]["lapse_reason"] == "due_journal_cancelled"
        )

    async def test_a_confirmed_event_journal_lapses_nothing(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Only *cancelled* counts, so the exclusion is not "is an event"."""
        creating_id, _ = task_anchors
        due_id = await create_journal(
            journal_repository, title="Meeting", days_offset=2
        )
        await mark_journal_as_event(
            async_connection, due_id, event_state=EventState.CONFIRMED
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.get("/api/tasks/upcoming")

        assert [resource["id"] for resource in response.json()["data"]] == [
            str(task_id)
        ]

    async def test_a_task_whose_due_journal_has_passed_is_not_listed(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The other lapse cause, which is also simply behind the window.

        Both reasons are asserted rather than one, because they exclude the same
        task and a rule that lost either would still pass a test that only
        checked the row was gone.
        """
        creating_id, _ = task_anchors
        past_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=past_id
        )

        upcoming = await authenticated_client.get("/api/tasks/upcoming")
        read_back = await authenticated_client.get(f"/api/tasks/{task_id}")

        assert upcoming.json()["data"] == []
        assert read_back.json()["data"]["attributes"]["lapse_reason"] == "date_passed"

    async def test_another_users_task_is_never_listed(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Owner scoping is the statement's, and both users have one due."""
        creating_id, _ = task_anchors
        mine_journal = await create_journal(
            journal_repository, title="Mine", days_offset=2
        )
        mine = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=mine_journal,
        )
        theirs_journal = await create_journal(
            journal_repository, title="Theirs", days_offset=2, user_id=OTHER_USER_ID
        )
        await create_task(
            async_connection,
            creating_journal_id=theirs_journal,
            due_journal_id=theirs_journal,
            user_id=OTHER_USER_ID,
        )

        response = await authenticated_client.get("/api/tasks/upcoming")

        assert [resource["id"] for resource in response.json()["data"]] == [str(mine)]

    async def test_rows_are_ordered_soonest_first(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The specification's order, all the way to the wire."""
        creating_id, _ = task_anchors
        far_id = await create_journal(journal_repository, title="Friday", days_offset=5)
        near_id = await create_journal(
            journal_repository, title="Tomorrow", days_offset=1
        )
        far_task = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=far_id
        )
        near_task = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=near_id
        )

        response = await authenticated_client.get("/api/tasks/upcoming")

        assert [resource["id"] for resource in response.json()["data"]] == [
            str(near_task),
            str(far_task),
        ]

    async def test_same_day_rows_are_ordered_by_task_id(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The tie-break, which is the common case for a dashboard week.

        Two tasks due in the same journal share a date exactly, so the id is the
        only thing separating them and the order would otherwise be whatever
        PostgreSQL happened to find.
        """
        creating_id, _ = task_anchors
        due_id = await create_journal(
            journal_repository, title="Tuesday", days_offset=2
        )
        first = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        second = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.get("/api/tasks/upcoming")

        assert [resource["id"] for resource in response.json()["data"]] == [
            str(first),
            str(second),
        ]

    async def test_each_row_carries_an_absolute_self_link(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """One ``links.self`` shape across every task route."""
        creating_id, _ = task_anchors
        due_id = await create_journal(journal_repository, title="Soon", days_offset=2)
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.get("/api/tasks/upcoming")

        self_link = response.json()["data"][0]["links"]["self"]
        assert self_link.startswith("http")
        assert self_link.endswith(f"/api/tasks/{task_id}")

    async def test_an_empty_window_is_a_200_not_a_404(
        self, authenticated_client: AsyncClient
    ):
        """Nothing due this week is a good outcome, and still names the window."""
        response = await authenticated_client.get("/api/tasks/upcoming")

        assert response.status_code == 200
        assert response.json()["data"] == []
        assert response.json()["meta"]["total"] == 0
        assert response.json()["meta"]["window"]["days_ahead"] == 7

    @pytest.mark.parametrize("days_ahead", [-1, 91])
    async def test_an_out_of_range_days_ahead_is_rejected(
        self, authenticated_client: AsyncClient, days_ahead: int
    ):
        """The bound that keeps this from becoming an unbounded task list."""
        response = await authenticated_client.get(
            f"/api/tasks/upcoming?days_ahead={days_ahead}"
        )

        assert response.status_code == 400

    async def test_days_ahead_of_zero_is_today_only(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """A single-day window is a legitimate ask, not an empty one."""
        creating_id, _ = task_anchors
        today_id = await create_journal(
            journal_repository, title="Today", days_offset=0
        )
        tomorrow_id = await create_journal(
            journal_repository, title="Tomorrow", days_offset=1
        )
        today_task = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=today_id
        )
        await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=tomorrow_id,
        )

        response = await authenticated_client.get("/api/tasks/upcoming?days_ahead=0")

        assert [resource["id"] for resource in response.json()["data"]] == [
            str(today_task)
        ]
