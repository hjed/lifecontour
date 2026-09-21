"""The grace an unanswered import waits out, against what it has to outlast."""

import inspect

from core_shared.stream_consumer import StreamConsumer

from snipeit_sync_service import IMPORT_LINK_GRACE_SECONDS


def _redelivery_budget_seconds() -> float:
    """How long the stream can take to finish with an event it has delivered.

    Read from the shared consumer's own defaults rather than restated, because
    the point of the test is that the two move together.
    """
    parameters = inspect.signature(StreamConsumer.__init__).parameters
    idle_ms: int = parameters["retry_min_idle_ms"].default
    attempts: int = parameters["max_delivery_count"].default
    return idle_ms * attempts / 1000


def test_the_import_grace_outlasts_the_streams_redelivery_budget() -> None:
    """A create still due for redelivery must not be treated as never coming.

    The inbound consumer reclaims a pending entry after ``retry_min_idle_ms``
    and dead-letters it — without replay — once it has been delivered
    ``max_delivery_count`` times, so an event the backend has not finished with
    is resolved one way or the other inside that budget.

    Importing the record before then would race a create that is still going to
    arrive. The link the import writes turns that redelivery into an update, so
    the record's older state would be written over the recovered journal, and
    nothing would correct it: the row's hash by then says the journal already
    holds the record's current state, so every later sync skips it.

    This fails if either side is tuned without the other.
    """
    assert IMPORT_LINK_GRACE_SECONDS > _redelivery_budget_seconds()
