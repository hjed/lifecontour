"""Unit tests for resolving the name of a task a history row is about.

A contact's activity feed shows rows whose subject is a **task**, and the row
itself cannot name it: both its values are the *contact's* id, and the task's
text lives on a different row. Without a name the entry reads "Linked to a
task" and points at nothing the reader can identify — the specification asks
for the task to be surfaced on the contact's history, not for an anonymous
line saying one exists.

The name is resolved from ``field_history`` itself rather than from ``tasks``.
That is not a convenience: a task is hard-deleted, and the entry a deleted task
leaves behind is exactly the one that most needs naming.
"""

from app.core.history.models import CREATED_MARKER, resolve_task_label


class TestResolveTaskLabel:
    def test_the_creation_marker_names_a_task_that_was_never_reworded(self) -> None:
        rows = [(CREATED_MARKER, "Book the venue", "2024-01-01T09:00:00+00:00")]

        assert resolve_task_label(rows) == "Book the venue"

    def test_the_latest_reword_wins_over_the_creation_marker(self) -> None:
        """The label names the task as it last stood, not as it was born.

        A record of a link is most useful when it names the commitment the
        reader would recognise, which is its current wording.
        """
        rows = [
            (CREATED_MARKER, "Book the venue", "2024-01-01T09:00:00+00:00"),
            ("text", "Book the hall", "2024-01-02T09:00:00+00:00"),
            ("text", "Book the other hall", "2024-01-03T09:00:00+00:00"),
        ]

        assert resolve_task_label(rows) == "Book the other hall"

    def test_rows_arriving_out_of_order_still_resolve_to_the_latest(self) -> None:
        rows = [
            ("text", "Book the other hall", "2024-01-03T09:00:00+00:00"),
            (CREATED_MARKER, "Book the venue", "2024-01-01T09:00:00+00:00"),
            ("text", "Book the hall", "2024-01-02T09:00:00+00:00"),
        ]

        assert resolve_task_label(rows) == "Book the other hall"

    def test_a_reword_to_nothing_falls_back_rather_than_erasing_the_name(self) -> None:
        """A ``None`` on the newest row is not a name, and not an answer either."""
        rows = [
            (CREATED_MARKER, "Book the venue", "2024-01-01T09:00:00+00:00"),
            ("text", None, "2024-01-02T09:00:00+00:00"),
        ]

        assert resolve_task_label(rows) == "Book the venue"

    def test_a_task_with_no_naming_row_resolves_to_nothing(self) -> None:
        """Not an error: projection lags, so a task can have no rows yet.

        The surface renders the unnamed wording rather than a placeholder.
        """
        assert resolve_task_label([]) is None
        assert (
            resolve_task_label([("status", "done", "2024-01-01T09:00:00+00:00")])
            is None
        )

    def test_a_row_with_no_timestamp_is_ordered_last_rather_than_dropped(self) -> None:
        """``created_at`` is nullable on the way in; a name is better than none."""
        rows = [(CREATED_MARKER, "Book the venue", None)]

        assert resolve_task_label(rows) == "Book the venue"
