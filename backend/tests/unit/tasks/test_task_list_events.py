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
