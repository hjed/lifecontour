"""Every domain event the tasks module publishes, found rather than listed.

Three separate claims are made about this set — the projection has a handler for
each type, the ``history-projection`` group subscribes to each, and the
``search-indexer`` group matches none of them — across three test files. A list
written down in each is three lists to remember to extend, and this domain has
already been caught out by a hand-maintained one: the count that decided how many
event types tasks needed enumerated the writes on ``TaskService`` and missed the
one the journal domain performs on a task when it merges journals.

Reading the module instead means the day a new event class lands is the day those
three tests fail, rather than the day somebody notices a task's history is
missing a change.
"""

import inspect
from collections.abc import Mapping, Sequence
from types import ModuleType
from typing import Any, get_origin

from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskIcon, TaskJournalRepointing, TaskStatus

from app.core.tasks.models import events as task_events
from app.core.tasks.models import task_list_events
from app.core.tasks.models.events import DomainEvent, TaskJournalLinkOrigin

# Sample values by annotation, used to build one of each event class. Anything
# unrecognised raises rather than being skipped, so a new event carrying a new
# kind of argument is a loud failure instead of a silent hole in the inventory.
_SAMPLE_ARGUMENTS: dict[Any, Any] = {
    int: 1,
    str: "x",
    TaskStatus: TaskStatus.NOT_DONE,
    TaskJournalLinkOrigin: TaskJournalLinkOrigin.MANUAL,
    Provenance: Provenance.SYSTEM,
    # A list's icon, optional on ``TaskListCreated``.
    TaskIcon | None: None,
    # A merge's summary for one task. It has to record *something* — the value
    # object refuses one that records nothing — so the sample names the plainest
    # outcome rather than an all-default instance.
    TaskJournalRepointing: TaskJournalRepointing(
        task_id=1, user_id="x", due_anchor_moved=True
    ),
}


def _event_classes_defined_in(module: ModuleType) -> list[type[DomainEvent]]:
    """Every ``DomainEvent`` subclass **defined in** ``module``.

    The ``__module__`` check is what makes "defined in" true rather than
    "visible from". The tasks module declares its own local ``DomainEvent`` base,
    so an imported journal or contact event would not match today — but the three
    bases are identical and the duplication is recorded as deliberate, so the day
    they are unified an import would quietly enter this inventory and every claim
    made about it would widen without anybody choosing that. The same check keeps
    the task-list module's events out of the task inventory and the task events
    it imports out of the list one.
    """
    return [
        member
        for member in vars(module).values()
        if isinstance(member, type)
        and issubclass(member, DomainEvent)
        and member is not DomainEvent
        and member.__module__ == module.__name__
    ]


def task_event_classes() -> list[type[DomainEvent]]:
    """Every event class the tasks events module defines — task history."""
    return _event_classes_defined_in(task_events)


def task_list_event_classes() -> list[type[DomainEvent]]:
    """Every event class the task-list events module defines — list history.

    A list is its own aggregate, filed under ``entity_type='task_list'``, so its
    events are inventoried separately rather than widening the task set every
    task-history claim is made about.
    """
    return _event_classes_defined_in(task_list_events)


def _argument_for(parameter: inspect.Parameter) -> Any:
    annotation = parameter.annotation
    if annotation in _SAMPLE_ARGUMENTS:
        return _SAMPLE_ARGUMENTS[annotation]
    if get_origin(annotation) in (dict, Mapping):
        return {}
    if get_origin(annotation) in (list, Sequence):
        return []
    raise AssertionError(
        f"No sample value for {parameter.name}: {annotation!r}. Add one to "
        "tests/task_event_inventory.py so the inventory keeps covering every "
        "task event type."
    )


def _event_types_by_class(classes: list[type[DomainEvent]]) -> dict[str, str]:
    """Each task event class name mapped to the ``event_type`` it publishes.

    ``event_type`` is a constructor argument rather than a class attribute, so
    the only way to read it is to build one — and the arguments come from the
    signature rather than being spelt out per class, for the reason the module
    docstring gives.
    """
    built: dict[str, str] = {}
    for cls in classes:
        parameters = inspect.signature(cls.__init__).parameters
        kwargs = {
            name: _argument_for(parameter)
            for name, parameter in parameters.items()
            if name != "self" and parameter.default is inspect.Parameter.empty
        }
        built[cls.__name__] = cls(**kwargs).event_type
    return built


def task_event_types_by_class() -> dict[str, str]:
    """Each task event class name mapped to the ``event_type`` it publishes."""
    return _event_types_by_class(task_event_classes())


def task_event_types() -> set[str]:
    """The ``event_type`` string of every task domain event."""
    return set(task_event_types_by_class().values())


def task_list_event_types_by_class() -> dict[str, str]:
    """Each task-list event class name mapped to the ``event_type`` it publishes."""
    return _event_types_by_class(task_list_event_classes())


def task_list_event_types() -> set[str]:
    """The ``event_type`` string of every task-list domain event."""
    return set(task_list_event_types_by_class().values())
