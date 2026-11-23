"""Unit tests for the task list domain events.

A list is its own aggregate, so its events live in their own module rather than
beside the task events (see :mod:`app.core.tasks.models.task_list_events`). These
tests pin what the rest of the pipeline will read: the whole payload, compared
key for key, and its JSON round trip, because the payload reaches every reader
through ``outbox_events.event_data`` and a Redis stream.
"""

import json

from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskIcon

from app.core.tasks.models.task_list_events import (
    TASK_LIST_EVENT_TYPES,
    TaskListCreated,
    TaskListDeleted,
    TaskListUpdated,
)

LIST_ID = 7
USER_ID = "user-123"
NAME = "Packing"


def make_created(
    *,
    icon: TaskIcon | None = TaskIcon.LUGGAGE,
    source: Provenance | None = None,
    changed_by: str | None = None,
) -> TaskListCreated:
    if source is None or changed_by is None:
        return TaskListCreated(
            task_list_id=LIST_ID, user_id=USER_ID, name=NAME, icon=icon
        )
    return TaskListCreated(
        task_list_id=LIST_ID,
        user_id=USER_ID,
        name=NAME,
        icon=icon,
        source=source,
        changed_by=changed_by,
    )


class TestTaskListCreated:
    def test_identifies_itself_as_a_task_list_created_event(self) -> None:
        event = make_created()

        assert event.event_type == "TaskListCreated"
        assert event.event_id.startswith(f"task_list_created_{LIST_ID}_")

    def test_its_type_is_in_the_published_set(self) -> None:
        """The set a future subscriber reads must name every list event."""
        assert make_created().event_type in TASK_LIST_EVENT_TYPES

    def test_aggregate_id_is_the_integer_list_id(self) -> None:
        event = make_created()

        assert event.aggregate_id == LIST_ID
        assert isinstance(event.aggregate_id, int)

    def test_payload_carries_exactly_the_documented_keys(self) -> None:
        """Whole-key, so a renamed or added key fails here first.

        Position is deliberately absent: reordering publishes nothing, so a
        position recorded at creation would read as current long after it
        stopped being so.
        """
        event = make_created()

        assert event.event_data == {
            "task_list_id": LIST_ID,
            "user_id": USER_ID,
            "name": NAME,
            "icon": TaskIcon.LUGGAGE.value,
            "source": Provenance.SYSTEM.value,
            "changed_by": "system",
        }

    def test_a_list_without_an_icon_carries_null(self) -> None:
        event = make_created(icon=None)

        assert event.event_data["icon"] is None

    def test_provenance_and_actor_are_carried(self) -> None:
        event = make_created(source=Provenance.MCP, changed_by="mcp")

        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"

    def test_the_payload_survives_a_json_round_trip(self) -> None:
        event = make_created()

        assert json.loads(json.dumps(event.event_data)) == event.event_data


def make_updated(
    changed_fields: dict[str, tuple[str | None, str | None]] | None = None,
    *,
    source: Provenance | None = None,
    changed_by: str | None = None,
) -> TaskListUpdated:
    fields: dict[str, tuple[str | None, str | None]] = (
        changed_fields if changed_fields is not None else {"name": ("Old", "New")}
    )
    if source is None or changed_by is None:
        return TaskListUpdated(
            task_list_id=LIST_ID, user_id=USER_ID, changed_fields=fields
        )
    return TaskListUpdated(
        task_list_id=LIST_ID,
        user_id=USER_ID,
        changed_fields=fields,
        source=source,
        changed_by=changed_by,
    )


class TestTaskListUpdated:
    def test_identifies_itself_as_a_task_list_updated_event(self) -> None:
        event = make_updated()

        assert event.event_type == "TaskListUpdated"
        assert event.event_id.startswith(f"task_list_updated_{LIST_ID}_")

    def test_its_type_is_in_the_published_set(self) -> None:
        assert make_updated().event_type in TASK_LIST_EVENT_TYPES

    def test_aggregate_id_is_the_integer_list_id(self) -> None:
        event = make_updated()

        assert event.aggregate_id == LIST_ID
        assert isinstance(event.aggregate_id, int)

    def test_payload_carries_exactly_the_documented_keys(self) -> None:
        """Whole-key: the changes as ``{field: (old, new)}`` and the actor."""
        event = make_updated(
            {"name": ("Old", "New"), "icon": (None, TaskIcon.LUGGAGE.value)}
        )

        assert event.event_data == {
            "task_list_id": LIST_ID,
            "user_id": USER_ID,
            "changed_fields": {
                "name": ("Old", "New"),
                "icon": (None, TaskIcon.LUGGAGE.value),
            },
            "source": Provenance.SYSTEM.value,
            "changed_by": "system",
        }

    def test_a_cleared_icon_carries_null_as_the_new_value(self) -> None:
        event = make_updated({"icon": (TaskIcon.LUGGAGE.value, None)})

        assert event.event_data["changed_fields"] == {
            "icon": (TaskIcon.LUGGAGE.value, None)
        }

    def test_provenance_and_actor_are_carried(self) -> None:
        event = make_updated(source=Provenance.UI, changed_by="ui")

        assert event.event_data["source"] == "ui"
        assert event.event_data["changed_by"] == "ui"

    def test_the_payload_survives_a_json_round_trip(self) -> None:
        """The pairs arrive as lists, which is what the history projection reads."""
        event = make_updated(
            {"name": ("Old", "New"), "icon": (TaskIcon.LUGGAGE.value, None)}
        )

        assert json.loads(json.dumps(event.event_data))["changed_fields"] == {
            "name": ["Old", "New"],
            "icon": [TaskIcon.LUGGAGE.value, None],
        }

    def test_archiving_and_unarchiving_carry_archived_at_as_iso_or_null(
        self,
    ) -> None:
        """Archive state travels as ``archived_at``: ``(null, ts)`` archives,
        ``(ts, null)`` unarchives — plain strings the history projection reads."""
        archived_at = "2026-11-21T09:30:00+00:00"

        archived = make_updated({"archived_at": (None, archived_at)})
        unarchived = make_updated({"archived_at": (archived_at, None)})

        assert json.loads(json.dumps(archived.event_data))["changed_fields"] == {
            "archived_at": [None, archived_at]
        }
        assert json.loads(json.dumps(unarchived.event_data))["changed_fields"] == {
            "archived_at": [archived_at, None]
        }


def make_deleted(
    *,
    deleted_task_count: int = 3,
    kept_task_count: int = 1,
    source: Provenance | None = None,
    changed_by: str | None = None,
) -> TaskListDeleted:
    if source is None or changed_by is None:
        return TaskListDeleted(
            task_list_id=LIST_ID,
            user_id=USER_ID,
            name=NAME,
            deleted_task_count=deleted_task_count,
            kept_task_count=kept_task_count,
        )
    return TaskListDeleted(
        task_list_id=LIST_ID,
        user_id=USER_ID,
        name=NAME,
        deleted_task_count=deleted_task_count,
        kept_task_count=kept_task_count,
        source=source,
        changed_by=changed_by,
    )


class TestTaskListDeleted:
    def test_identifies_itself_as_a_task_list_deleted_event(self) -> None:
        event = make_deleted()

        assert event.event_type == "TaskListDeleted"
        assert event.event_id.startswith(f"task_list_deleted_{LIST_ID}_")

    def test_its_type_is_in_the_published_set(self) -> None:
        """So the history projection, which subscribes to the set, receives it."""
        assert make_deleted().event_type in TASK_LIST_EVENT_TYPES

    def test_aggregate_id_is_the_integer_list_id(self) -> None:
        event = make_deleted()

        assert event.aggregate_id == LIST_ID
        assert isinstance(event.aggregate_id, int)

    def test_payload_carries_exactly_the_documented_keys(self) -> None:
        """Whole-key. The list row is gone once this is read, so the owner and
        the name travel on the event: they are all a "deleted" history line
        has to go on."""
        event = make_deleted(deleted_task_count=3, kept_task_count=1)

        assert event.event_data == {
            "task_list_id": LIST_ID,
            "user_id": USER_ID,
            "name": NAME,
            "deleted_task_count": 3,
            "kept_task_count": 1,
            "source": Provenance.SYSTEM.value,
            "changed_by": "system",
        }

    def test_provenance_and_actor_are_carried(self) -> None:
        event = make_deleted(source=Provenance.MCP, changed_by="mcp")

        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"

    def test_the_payload_survives_a_json_round_trip(self) -> None:
        event = make_deleted()

        assert json.loads(json.dumps(event.event_data)) == event.event_data
