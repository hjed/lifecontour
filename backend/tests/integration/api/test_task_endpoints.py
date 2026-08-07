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

import pytest
from core_shared.models.tasks import TaskStatus
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from tests.integration.tasks.task_seeding import (
    COUNT_CONTACT_LINKS,
    COUNT_INTERMEDIATE_JOURNALS,
    COUNT_TASKS,
    FIXED_PAST_INSTANT,
    OTHER_USER_ID,
    USER_ID,
    count,
    create_contact,
    create_journal,
    create_task,
    link_contact,
    link_intermediate_journal,
    stored_status,
    stored_text,
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
