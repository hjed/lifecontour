"""The completeness rule: every task write path announces what it did.

With contact links published, the specification's full event set is in place —
created, text updated, status changed, due journal retargeted, journal
linked/unlinked, contact linked/unlinked, deleted. This file is what stops that
being a claim made once and left to rot.

**The rule, as the journal-link phase restated it:** *every task write path
publishes at least one event, and a retarget publishes exactly two — the journal
it retains, then the anchor move, in that order.* The "at least one" is not a
licence for two elsewhere: **no other write path may publish more than one**, and
that half is what stops the retarget's exception spreading, so it is asserted
per path rather than in aggregate.

**Written against the write paths, not against** ``TaskService``\\ **'s method
list**, which is the requirement the iteration document is explicit about and the
reason this file exists rather than a class in the events file. A test that
enumerated service methods would have passed for years while a **journal merge**
re-pointed task anchors from another domain entirely and published nothing — the
gap that went unnoticed until a later phase's review, and that this file carried
as a named exclusion until the phase that closed it. So the inventory below is
anchored to the **repository ports**: every mutating method on
``TaskRepository`` and ``TaskAnchorRepository`` must be classified, either as
reached by a covered path or as a **named exclusion**. Adding a write method to
either port fails :class:`TestEveryPortWriteIsAccountedFor` until somebody says
which it is.

**One path is driven from another domain**, and it is the one that vindicates
the paragraph above: the merge write path calls ``JournalMergeService``, because
that is where the write is reached from. Every other path goes through
``TaskService``.

**A separate file from** ``test_task_events_integration.py`` deliberately: that
file asks "what did *this* operation publish?" one operation at a time, and this
one asks "is anything unaccounted for?" across all of them. The inventory is the
subject here, and burying it in a 2,000-line file is how it would stop being
read.

**Facts, not type names.** Contact membership travels as a ``TaskUpdated``
carrying ``changed_fields``, the same type a reword uses, so an inventory
comparing event *types* would call a contact link and a text change the same
thing and would still pass if the service published the wrong one. Each path
therefore declares the **fact** it announces, derived from the payload by
:func:`_fact`.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskStatus
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_relationship_repository import (
    SqlContactRelationshipRepository,
)
from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.contacts.services.contact_merge_service import ContactMergeService
from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.services.history_service import _HANDLERS
from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.core.tasks.adapters.sql.task_contact_repository import (
    SqlTaskContactRepository,
)
from app.core.tasks.models.events import contact_field_name
from app.core.tasks.models.repositories import (
    TaskAnchorRepository,
    TaskContactRepository,
    TaskRepository,
)
from app.core.tasks.services.task_contact_merge_service import (
    TaskContactMergeService,
)
from app.core.tasks.services.task_journal_merge_service import (
    TaskJournalMergeService,
)
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.events.history_projection_consumer import (
    TASK_HISTORY_EVENT_TYPES,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.tasks.task_seeding import (
    FIXED_PAST_INSTANT,
    USER_ID,
    TaskEventRow,
    create_contact,
    create_journal,
    stored_anchors,
    task_events,
)

TASK_TEXT = "book the belay course"
UPDATED_TEXT = "book the belay course and the refresher"


# --------------------------------------------------------------------------
# What a stored event says happened
# --------------------------------------------------------------------------


def _fact(event: TaskEventRow) -> str:
    """The thing an event announces, as a consumer would have to work it out.

    ``TaskUpdated`` covers three different facts, so the type alone is not an
    answer for it — the key inside ``changed_fields`` is. Deriving the fact the
    way a projection would is what makes the inventory below an assertion about
    behaviour rather than about class names.
    """
    if event.event_type != "TaskUpdated":
        return {
            "TaskCreated": "created",
            "TaskDueJournalRetargeted": "retargeted",
            "TaskJournalLinked": "journal-linked",
            "TaskJournalUnlinked": "journal-unlinked",
            # A merge announces one fact however many of the task's links moved:
            # what happened to the task is that a journal it was on became
            # another journal. Which links moved is in ``changed_fields``, and
            # the payload tests are where that belongs.
            "TaskJournalLinksRepointed": "journals-repointed",
            "TaskDeleted": "deleted",
        }[event.event_type]

    changed = sorted(event.payload["changed_fields"])
    facts = [
        "contact-changed" if key.startswith("contact:") else key for key in changed
    ]
    return f"updated:{'+'.join(facts)}"


async def _facts(connection: AsyncConnection, task_id: int) -> list[str]:
    """Everything published about one task, oldest first, as facts."""
    return [_fact(event) for event in await task_events(connection, task_id=task_id)]


# --------------------------------------------------------------------------
# The inventory
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Seeded:
    """What a scenario's arrangement leaves for its action to act on.

    A dataclass rather than a bare task id because most paths need something
    else too — a journal to link, a contact to remove — and threading those
    through a tuple would make the inventory below unreadable.
    """

    task_id: int
    journal_id: int = 0
    contact_id: int = 0
    # The contact a merge absorbs ``contact_id`` into. A second field rather
    # than reusing ``journal_id``'s trick of "the other one", because a contact
    # merge names both people and reading it back off a journal-shaped field is
    # how the two would eventually be passed the wrong way round.
    survivor_contact_id: int = 0


@dataclass(frozen=True)
class WritePath:
    """One way a task row or a task link row can change.

    **Split into ``seed`` and ``act`` deliberately.** An earlier draft ran the
    whole scenario in one callable and compared every event the task had ever
    published, and the mutation check found what that cost: almost every
    scenario has to *create* a task before it can act on one, so "this path
    published something" was true of all eleven the moment ``create_task``
    worked — an assertion that could not fail for ten of them. Recording the
    facts between the two halves makes ``expects`` the **operation's own**
    output, so removing a publish call fails the path that lost it rather than
    being absorbed by the create's event sitting in front of it.

    ``ports`` names the repository methods the path reaches. It is not
    decoration: it is the join between this inventory and
    :class:`TestEveryPortWriteIsAccountedFor`, which is what makes "we listed
    every write path" checkable rather than asserted.
    """

    name: str
    ports: frozenset[str]
    seed: Callable[[_Fixtures], Awaitable[Seeded]]
    act: Callable[[_Fixtures, Seeded], Awaitable[None]]
    expects: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Fixtures:
    """What every scenario below needs, gathered so a callable takes one argument."""

    service: TaskService
    connection: AsyncConnection
    journals: SqlJournalRepository
    anchors: tuple[int, int]
    # The journal domain's merge, because one write path is reached from there
    # rather than from ``TaskService`` — which is the whole reason this
    # inventory keys on repository methods rather than on service methods.
    merges: JournalMergeService
    # The contacts domain's merge, for the same reason and from a third domain:
    # it moves a task's contact links before deleting the absorbed person.
    contact_merges: ContactMergeService


async def _seed_task(
    fixtures: _Fixtures, *, contact_ids: list[int] | None = None
) -> int:
    """A task to act on, created through the service so its anchors are real."""
    creating_id, due_id = fixtures.anchors
    created = await fixtures.service.create_task(
        user_id=USER_ID,
        creating_journal_id=creating_id,
        due_journal_id=due_id,
        text=TASK_TEXT,
        transaction=fixtures.connection,
        contact_ids=contact_ids,
    )
    assert created.id is not None
    return created.id


async def _seed_nothing(fixtures: _Fixtures) -> Seeded:
    """For the two paths whose *action* is the create itself."""
    return Seeded(task_id=0)


async def _seed_bare_task(fixtures: _Fixtures) -> Seeded:
    return Seeded(task_id=await _seed_task(fixtures))


async def _seed_task_and_journal(fixtures: _Fixtures) -> Seeded:
    task_id = await _seed_task(fixtures)
    journal_id = await create_journal(
        fixtures.journals, title="Where it came up", days_offset=3
    )
    return Seeded(task_id=task_id, journal_id=journal_id)


async def _seed_task_and_contact(fixtures: _Fixtures) -> Seeded:
    task_id = await _seed_task(fixtures)
    return Seeded(task_id=task_id, contact_id=await create_contact(fixtures.connection))


async def _act_create(fixtures: _Fixtures, seeded: Seeded) -> None:
    await _seed_task(fixtures)


async def _act_create_with_contacts(fixtures: _Fixtures, seeded: Seeded) -> None:
    contact_id = await create_contact(fixtures.connection)
    await _seed_task(fixtures, contact_ids=[contact_id])


async def _act_update_text(fixtures: _Fixtures, seeded: Seeded) -> None:
    await fixtures.service.update_task(
        user_id=USER_ID,
        task_id=seeded.task_id,
        text=UPDATED_TEXT,
        transaction=fixtures.connection,
    )


async def _act_set_status(fixtures: _Fixtures, seeded: Seeded) -> None:
    await fixtures.service.set_status(
        user_id=USER_ID,
        task_id=seeded.task_id,
        status=TaskStatus.DONE,
        transaction=fixtures.connection,
    )


async def _act_retarget(fixtures: _Fixtures, seeded: Seeded) -> None:
    later_id = await create_journal(
        fixtures.journals, title="Where it matters now", days_offset=21
    )
    await fixtures.service.retarget_due_journal(
        user_id=USER_ID,
        task_id=seeded.task_id,
        due_journal_id=later_id,
        transaction=fixtures.connection,
    )


async def _seed_task_already_back_where_it_started(fixtures: _Fixtures) -> Seeded:
    """A task that has left its due journal and returned to it.

    The arrangement for the A→B→A case: after these two moves the original due
    journal is *both* the anchor again and an intermediate link left over from
    the first departure.
    """
    _, due_id = fixtures.anchors
    task_id = await _seed_task(fixtures)
    second_id = await create_journal(
        fixtures.journals, title="The second stop", days_offset=21
    )
    await fixtures.service.retarget_due_journal(
        user_id=USER_ID,
        task_id=task_id,
        due_journal_id=second_id,
        transaction=fixtures.connection,
    )
    await fixtures.service.retarget_due_journal(
        user_id=USER_ID,
        task_id=task_id,
        due_journal_id=due_id,
        transaction=fixtures.connection,
    )
    return Seeded(task_id=task_id)


async def _act_retarget_away_again(fixtures: _Fixtures, seeded: Seeded) -> None:
    """The third move, whose retained journal is already linked.

    A retarget only ever *adds* an intermediate link, so leaving a journal the
    task has already left finds it still attached, writes no row, and publishes
    only the anchor move. This is why the rule is "exactly two **when a link row
    was written**" rather than "always two", and why the inventory carries the
    case rather than a sentence about it.
    """
    third_id = await create_journal(
        fixtures.journals, title="The third stop", days_offset=28
    )
    await fixtures.service.retarget_due_journal(
        user_id=USER_ID,
        task_id=seeded.task_id,
        due_journal_id=third_id,
        transaction=fixtures.connection,
    )


async def _act_attach_journal(fixtures: _Fixtures, seeded: Seeded) -> None:
    await fixtures.service.attach_intermediate_journal(
        user_id=USER_ID,
        task_id=seeded.task_id,
        journal_id=seeded.journal_id,
        transaction=fixtures.connection,
    )


async def _seed_task_with_an_attached_journal(fixtures: _Fixtures) -> Seeded:
    seeded = await _seed_task_and_journal(fixtures)
    await _act_attach_journal(fixtures, seeded)
    return seeded


async def _act_detach_journal(fixtures: _Fixtures, seeded: Seeded) -> None:
    await fixtures.service.detach_intermediate_journal(
        user_id=USER_ID,
        task_id=seeded.task_id,
        journal_id=seeded.journal_id,
        transaction=fixtures.connection,
    )


async def _act_link_contact(fixtures: _Fixtures, seeded: Seeded) -> None:
    await fixtures.service.link_contact(
        user_id=USER_ID,
        task_id=seeded.task_id,
        contact_id=seeded.contact_id,
        transaction=fixtures.connection,
    )


async def _seed_task_with_a_linked_contact(fixtures: _Fixtures) -> Seeded:
    contact_id = await create_contact(fixtures.connection)
    task_id = await _seed_task(fixtures, contact_ids=[contact_id])
    return Seeded(task_id=task_id, contact_id=contact_id)


async def _act_unlink_contact(fixtures: _Fixtures, seeded: Seeded) -> None:
    await fixtures.service.unlink_contact(
        user_id=USER_ID,
        task_id=seeded.task_id,
        contact_id=seeded.contact_id,
        transaction=fixtures.connection,
    )


async def _act_delete(fixtures: _Fixtures, seeded: Seeded) -> None:
    await fixtures.service.delete_task(
        user_id=USER_ID, task_id=seeded.task_id, transaction=fixtures.connection
    )


async def _seed_task_and_a_journal_to_merge_into(fixtures: _Fixtures) -> Seeded:
    """A task, and a survivor for the journal it is due in to be absorbed into.

    ``journal_id`` carries the survivor here rather than something to link,
    because the merge names the journal the task is *not* on.
    """
    task_id = await _seed_task(fixtures)
    survivor_id = await create_journal(
        fixtures.journals, title="The surviving journal", days_offset=30
    )
    return Seeded(task_id=task_id, journal_id=survivor_id)


async def _act_merge_the_due_journal_away(fixtures: _Fixtures, seeded: Seeded) -> None:
    """The one action in this inventory performed by another domain.

    A journal merge moves the task's due anchor onto the survivor. It goes
    through the *journal* service rather than the tasks domain's own merge
    service, because what this inventory is about is that every write reaching
    the task tables announces itself — and the write is reached from here.
    """
    _, due_id = fixtures.anchors
    await fixtures.merges.merge_journals(
        target_id=seeded.journal_id,
        source_id=due_id,
        transaction=fixtures.connection,
        source=Provenance.UI,
        changed_by="ui",
    )


async def _seed_task_and_a_contact_to_merge_into(fixtures: _Fixtures) -> Seeded:
    """A task naming one person, and the person they are about to be merged into."""
    absorbed_id = await create_contact(fixtures.connection, first_name="Sarah")
    task_id = await _seed_task(fixtures, contact_ids=[absorbed_id])
    survivor_id = await create_contact(fixtures.connection, first_name="Sara")
    return Seeded(
        task_id=task_id, contact_id=absorbed_id, survivor_contact_id=survivor_id
    )


async def _act_merge_the_contact_away(fixtures: _Fixtures, seeded: Seeded) -> None:
    """The second action in this inventory performed by another domain.

    A contact merge moves the task's links onto the survivor before deleting
    the absorbed person — whose ``ON DELETE CASCADE`` would otherwise take them.
    It goes through the *contacts* service rather than the tasks domain's own
    merge service for the reason the journal merge above does: the write is
    reached from there, and this inventory is about every write that reaches the
    task tables announcing itself.
    """
    await fixtures.contact_merges.merge_contacts(
        seeded.survivor_contact_id,
        seeded.contact_id,
        transaction=fixtures.connection,
        source=Provenance.UI,
        changed_by="ui",
    )


WRITE_PATHS: list[WritePath] = [
    WritePath(
        name="create",
        ports=frozenset({"save"}),
        seed=_seed_nothing,
        act=_act_create,
        expects=["created"],
    ),
    WritePath(
        name="create naming contacts",
        ports=frozenset({"save", "add_contacts"}),
        seed=_seed_nothing,
        act=_act_create_with_contacts,
        # One event, not one plus a link each. The people are a field of the
        # task the create announces, which is this phase's decision.
        expects=["created"],
    ),
    WritePath(
        name="reword",
        ports=frozenset({"save"}),
        seed=_seed_bare_task,
        act=_act_update_text,
        expects=["updated:text"],
    ),
    WritePath(
        name="status change",
        ports=frozenset({"save"}),
        seed=_seed_bare_task,
        act=_act_set_status,
        expects=["updated:status"],
    ),
    WritePath(
        name="retarget",
        ports=frozenset({"save", "add_intermediate_journal"}),
        seed=_seed_bare_task,
        act=_act_retarget,
        # The exception, and the only one: the link it retains, then the move.
        expects=["journal-linked", "retargeted"],
    ),
    WritePath(
        name="retarget whose retained journal is already linked",
        ports=frozenset({"save", "add_intermediate_journal"}),
        seed=_seed_task_already_back_where_it_started,
        act=_act_retarget_away_again,
        # No link row is written, so the exception does not apply and the move
        # publishes alone.
        expects=["retargeted"],
    ),
    WritePath(
        name="attach an intermediate journal",
        ports=frozenset({"save", "add_intermediate_journal"}),
        seed=_seed_task_and_journal,
        act=_act_attach_journal,
        expects=["journal-linked"],
    ),
    WritePath(
        name="detach an intermediate journal",
        ports=frozenset({"remove_intermediate_journal"}),
        seed=_seed_task_with_an_attached_journal,
        act=_act_detach_journal,
        expects=["journal-unlinked"],
    ),
    WritePath(
        name="link a contact",
        ports=frozenset({"add_contacts"}),
        seed=_seed_task_and_contact,
        act=_act_link_contact,
        expects=["updated:contact-changed"],
    ),
    WritePath(
        name="unlink a contact",
        ports=frozenset({"remove_contact"}),
        seed=_seed_task_with_a_linked_contact,
        act=_act_unlink_contact,
        expects=["updated:contact-changed"],
    ),
    WritePath(
        name="delete",
        ports=frozenset({"delete"}),
        seed=_seed_bare_task,
        act=_act_delete,
        expects=["deleted"],
    ),
    WritePath(
        name="journal merge",
        ports=frozenset({"repoint_journal_links"}),
        seed=_seed_task_and_a_journal_to_merge_into,
        act=_act_merge_the_due_journal_away,
        # One fact, not a retarget's two: a merge moves the anchor and forces
        # nothing about the status. It is the only entry in this inventory whose
        # action is performed by another domain.
        expects=["journals-repointed"],
    ),
    WritePath(
        name="contact merge",
        ports=frozenset({"repoint_contact_links"}),
        seed=_seed_task_and_a_contact_to_merge_into,
        act=_act_merge_the_contact_away,
        # Two contact keys in one ``TaskUpdated``: the absorbed person leaves
        # and the survivor arrives. One event, because one thing happened to the
        # task — the person it names became somebody else.
        expects=["updated:contact-changed+contact-changed"],
    ),
]


# Reads are listed rather than inferred from the name, so a method called
# ``find_and_touch`` cannot classify itself as harmless.
PORT_READ_METHODS = frozenset(
    {
        "find_by_id",
        "find_by_id_for_update",
        "list_intermediate_journal_ids",
        "list_contact_ids",
        "find_tasks_for_journal",
        "list_intermediate_journal_ids_for_tasks",
        "list_contact_ids_for_tasks",
        "find_tasks_anchored_to_journal",
        # The upcoming-window query (ITER18-001 Phase 14). It landed on a branch
        # parallel to the one that added this inventory, so the merge left it
        # unclassified and the suite red — which is the guard working: a new port
        # method fails this test until somebody says which kind it is.
        "find_upcoming_tasks",
        # The journal list's tasks-due count (ITER18-001 Phase 21). Counts the
        # not-done tasks due in each of a page of journals; writes nothing and
        # publishes nothing, so there is no event to owe. The guard did its job
        # again here — this test was the phase's first failure.
        "count_not_done_tasks_by_due_journal",
        # The daily summary's past-day read (ITER18-005 Phase 5). Returns the
        # tasks due in a set of journals in every status, so that a summary of a
        # day gone by can say how each commitment resolved. It reads the current
        # rows and nothing else — no history replay, no write, no event — and the
        # guard caught it too, on the phase's first full integration run.
        "find_tasks_due_in_journals",
    }
)

# A write nobody announces, named so it is visible rather than merely absent.
#
# **Empty since ITER18-003 Phase 10**, and kept rather than deleted. Its one
# entry was ``repoint_journal_links`` — the merge write the journal domain
# performs on tasks — which now has a write path of its own below and an event
# per task it moves. What the mechanism is for outlives that entry: a write with
# no event should be *visible* rather than merely absent, and the test below
# refuses to let the list grow again without somebody choosing to add to it.
NAMED_EXCLUSIONS: dict[str, str] = {}


@pytest.fixture
def fixtures(
    service: TaskService,
    async_connection: AsyncConnection,
    journal_repository: SqlJournalRepository,
    task_anchors: tuple[int, int],
) -> _Fixtures:
    """Everything a scenario needs, so ``WritePath.run`` takes one argument."""
    return _Fixtures(
        service=service,
        connection=async_connection,
        journals=journal_repository,
        anchors=task_anchors,
        merges=JournalMergeService(
            journal_repo=journal_repository,
            event_publisher=OutboxEventPublisher(async_connection),
            task_merge_service=TaskJournalMergeService(
                task_anchor_repo=SqlTaskAnchorRepository(async_connection),
                event_publisher=OutboxEventPublisher(async_connection),
            ),
        ),
        contact_merges=ContactMergeService(
            contact_repo=SqlContactRepository(async_connection),
            relationship_repo=SqlContactRelationshipRepository(async_connection),
            journal_relationship_repo=SqlJournalContactRelationshipRepository(
                async_connection
            ),
            event_publisher=OutboxEventPublisher(async_connection),
            history_repo=SqlFieldHistoryRepository(async_connection),
            sync_metadata_repo=SyncMetadataRepository(async_connection),
            task_merge_service=TaskContactMergeService(
                task_contact_repo=SqlTaskContactRepository(async_connection),
                event_publisher=OutboxEventPublisher(async_connection),
            ),
        ),
    )


async def _run(
    path: WritePath, fixtures: _Fixtures, connection: AsyncConnection
) -> list[str]:
    """Arrange, record, act — and return only what the *action* announced.

    The recording between the two halves is the point: almost every action needs
    a task to act on, and a task cannot exist without a ``TaskCreated`` in front
    of it. Subtracting the arrangement is what makes the assertions below about
    the operation under test rather than about ``create_task`` still working.
    """
    seeded = await path.seed(fixtures)
    before = [_fact(event) for event in await task_events(connection)]

    await path.act(fixtures, seeded)

    after = [_fact(event) for event in await task_events(connection)]
    assert after[: len(before)] == before, (
        "the action rewrote history that was already there, which no task write "
        "should be able to do"
    )
    return after[len(before) :]


async def _published_types(
    path: WritePath, fixtures: _Fixtures, connection: AsyncConnection
) -> set[str]:
    """The ``event_type`` strings the *action* announced, arrangement subtracted.

    The sibling of :func:`_run`, which returns facts. Facts are the right unit for
    "did the path announce the right thing"; the projection is keyed on the type,
    so the projection questions need the type.
    """
    seeded = await path.seed(fixtures)
    before = len(await task_events(connection))

    await path.act(fixtures, seeded)

    return {event.event_type for event in (await task_events(connection))[before:]}


@pytest.mark.integration
class TestEveryWritePathPublishes:
    """Each path, run for real, against the events its action left behind."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", WRITE_PATHS, ids=lambda path: path.name)
    async def test_the_path_announces_exactly_what_it_did(
        self,
        fixtures: _Fixtures,
        async_connection: AsyncConnection,
        path: WritePath,
    ) -> None:
        """The facts, in order, with nothing extra and nothing missing.

        An equality rather than a subset check: "at least one event" would pass
        for a path that published five, and the half of the rule worth asserting
        is that no path but the retarget publishes more than one per write.
        """
        assert await _run(path, fixtures, async_connection) == path.expects

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", WRITE_PATHS, ids=lambda path: path.name)
    async def test_no_path_is_silent(
        self,
        fixtures: _Fixtures,
        async_connection: AsyncConnection,
        path: WritePath,
    ) -> None:
        """The rule's own words — *at least one event* — stated on its own.

        Implied by the equality above, and worth its own failure message: this is
        the assertion whose name a future reader meets when they add a write path
        and publish nothing from it.
        """
        assert await _run(path, fixtures, async_connection) != []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [path for path in WRITE_PATHS if path.name != "retarget"],
        ids=lambda path: path.name,
    )
    async def test_only_a_retarget_publishes_more_than_one_event(
        self,
        fixtures: _Fixtures,
        async_connection: AsyncConnection,
        path: WritePath,
    ) -> None:
        """The exception is one path wide, and this is what keeps it that way.

        The rule reads *"every task write path publishes at least one event, and
        a retarget publishes exactly two"*, and the second clause is not a
        licence for two elsewhere. Asserted against what each path **actually
        published** rather than against its declared ``expects``, because a
        change that made a second path publish twice would ordinarily arrive with
        its expectation updated to match — and would sail past a test that only
        read the list.
        """
        published = await _run(path, fixtures, async_connection)

        assert len(published) == 1, (
            f"{path.name} published {published}; only a retarget may publish more "
            "than one event for one write"
        )

    @pytest.mark.asyncio
    async def test_a_retarget_publishes_the_link_then_the_move(
        self,
        fixtures: _Fixtures,
        async_connection: AsyncConnection,
    ) -> None:
        """The exception itself, including its order.

        The journal it retains goes out **before** the anchor move, because each
        event is published directly behind the write it announces. A consumer
        reading the pair renders the trail in the order it happened.
        """
        path = next(path for path in WRITE_PATHS if path.name == "retarget")

        assert await _run(path, fixtures, async_connection) == [
            "journal-linked",
            "retargeted",
        ]


@pytest.mark.integration
class TestEveryPublishedEventIsProjected:
    """Nothing a write path announces is written to the stream and never read.

    The invariant is written in the form that *fails* for an unhandled task type,
    so the next one to arrive cannot land unprojected. The set is not closed —
    a journal merge re-points a task's anchors and will publish an event of its
    own — so a list of names here would be a list to remember to extend.

    This is the strongest of the three places the invariant is asserted, because
    it is driven by what the write paths **actually publish** against a real
    outbox. The unit-level versions read the event classes out of the module,
    which would still pass for a class nobody publishes; the pair of them can
    disagree only if a class exists that no path reaches, which
    :class:`TestEveryPortWriteIsAccountedFor` is the test for.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", WRITE_PATHS, ids=lambda path: path.name)
    async def test_the_types_this_path_publishes_all_have_a_handler(
        self,
        fixtures: _Fixtures,
        async_connection: AsyncConnection,
        path: WritePath,
    ) -> None:
        """A published type with no handler is projected as zero rows.

        ``HistoryService.project_event`` returns an empty list for a type it does
        not know, so the consumer acknowledges the event and writes nothing —
        a change missing from the user's history with nothing in the logs.
        """
        published = await _published_types(path, fixtures, async_connection)

        assert published <= set(_HANDLERS), (
            f"{path.name} publishes {sorted(published - set(_HANDLERS))}, which "
            "HistoryService has no handler for"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", WRITE_PATHS, ids=lambda path: path.name)
    async def test_the_types_this_path_publishes_are_all_subscribed(
        self,
        fixtures: _Fixtures,
        async_connection: AsyncConnection,
        path: WritePath,
    ) -> None:
        """The other half: a handler the consumer never delivers an event to.

        Both halves are needed and neither implies the other — a handler without
        a subscription writes history nobody reads, and a subscription without a
        handler reads an event nobody writes history for.
        """
        published = await _published_types(path, fixtures, async_connection)

        assert published <= set(TASK_HISTORY_EVENT_TYPES), (
            f"{path.name} publishes {sorted(published - set(TASK_HISTORY_EVENT_TYPES))}, "
            "which the history-projection group does not subscribe to"
        )


@pytest.mark.integration
class TestEveryPortWriteIsAccountedFor:
    """The structural half: a new write cannot land without being classified.

    This is what makes the inventory above a claim about the system rather than
    about the list somebody remembered to type. The ports are the narrowest place
    every task write must pass through — including one performed from another
    domain, which is what a service-method inventory would miss.
    """

    def test_every_port_method_is_a_read_or_a_classified_write(self) -> None:
        declared = (
            set(TaskRepository.__abstractmethods__)
            | set(TaskAnchorRepository.__abstractmethods__)
            | set(TaskContactRepository.__abstractmethods__)
        )
        covered = {port for path in WRITE_PATHS for port in path.ports}

        unclassified = declared - PORT_READ_METHODS - covered - set(NAMED_EXCLUSIONS)

        assert unclassified == set(), (
            "These repository methods are neither listed as reads nor reached by "
            "a write path nor named as an exclusion. If one of them writes, give "
            "it a WritePath and an event; if it reads, add it to "
            f"PORT_READ_METHODS: {sorted(unclassified)}"
        )

    def test_no_classification_names_a_method_that_no_longer_exists(self) -> None:
        """The other direction, so a rename leaves a stale entry rather than a hole.

        Without it, renaming ``add_contacts`` would leave the old name sitting in
        a ``WritePath.ports`` set, the new one would be unclassified, and only
        one of the two mistakes would be reported.
        """
        declared = (
            set(TaskRepository.__abstractmethods__)
            | set(TaskAnchorRepository.__abstractmethods__)
            | set(TaskContactRepository.__abstractmethods__)
        )
        claimed = (
            PORT_READ_METHODS
            | {port for path in WRITE_PATHS for port in path.ports}
            | set(NAMED_EXCLUSIONS)
        )

        assert claimed - declared == set()

    def test_no_write_goes_unannounced(self) -> None:
        """The list is empty, and stays empty by assertion rather than by habit.

        It held one entry for several phases: the merge re-point, the write the
        journal domain performs on task rows. Now that it publishes, there is no
        task write left that nothing announces — and a test allowing "a few"
        exclusions would let the next one be added as easily as that one was.
        """
        assert NAMED_EXCLUSIONS == {}

    @pytest.mark.asyncio
    async def test_a_merge_repoints_a_task_and_says_so(
        self,
        fixtures: _Fixtures,
        async_connection: AsyncConnection,
    ) -> None:
        """The inverted test, and the reason the gap was written down positively.

        It used to assert the opposite — that the re-point moved a task's due
        anchor and its history did not know — so that the day the gap closed,
        this failed and said so. It did. What it asserts now is the same two
        halves in agreement: the row moved, **and** the task announced it.

        Driven through the repository directly rather than through the merge,
        exactly as the negative version was, so the comparison between the two
        versions of this test is like for like: what changed is the behaviour of
        the write, not the way it is reached.
        """
        _, due_id = fixtures.anchors
        task_id = await _seed_task(fixtures)
        target_id = await create_journal(
            fixtures.journals, title="The surviving journal", days_offset=30
        )
        before = await _facts(async_connection, task_id)

        await fixtures.merges.merge_journals(
            target_id=target_id,
            source_id=due_id,
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )

        # The task really moved...
        _, moved_due_id = await stored_anchors(async_connection, task_id)
        assert moved_due_id == target_id
        # ...and its history now knows, in one line naming what moved.
        assert await _facts(async_connection, task_id) == [
            *before,
            "journals-repointed",
        ]


@pytest.mark.integration
class TestTheFactDerivationIsHonest:
    """``_fact`` is the inventory's only interpreter, so it needs its own tests.

    Every assertion above is filtered through it. If it read a contact change and
    a reword as the same string, the whole file would pass while the service
    published the wrong event — the failure mode a type-name comparison would
    have had, and the reason for deriving a fact at all.
    """

    def test_a_reword_and_a_contact_change_are_different_facts(self) -> None:
        reword = _make_update({"text": ["old", "new"]})
        contact = _make_update({contact_field_name(3): [None, 3]})

        assert _fact(reword) != _fact(contact)

    def test_two_contacts_read_as_the_same_kind_of_fact(self) -> None:
        """The fact is "a contact moved", not "contact 3 moved".

        Which person it was belongs to the payload assertions in the events file;
        here it would make every expectation depend on an id the seeding chose.
        """
        assert _fact(_make_update({contact_field_name(3): [None, 3]})) == _fact(
            _make_update({contact_field_name(9): [9, None]})
        )

    def test_a_combined_update_names_both_halves(self) -> None:
        combined = _make_update(
            {"text": ["old", "new"], "status": ["not_done", "done"]}
        )

        assert _fact(combined) == "updated:status+text"

    def test_an_unknown_event_type_raises_rather_than_being_ignored(self) -> None:
        """A silent default would let a new type join the stream unaccounted for.

        The inventory's whole purpose is that nothing arrives unnoticed, and a
        ``.get(type, "other")`` here would have quietly absorbed the next one.
        """
        with pytest.raises(KeyError):
            _fact(
                TaskEventRow(
                    event_id="x",
                    event_type="TaskSomethingNew",
                    aggregate_id=1,
                    payload={},
                    occurred_at=FIXED_PAST_INSTANT,
                )
            )


def _make_update(changed_fields: dict[str, list[object]]) -> TaskEventRow:
    """A stored ``TaskUpdated`` row, in the post-JSON form ``_fact`` receives."""
    return TaskEventRow(
        event_id="task_updated_1_x",
        event_type="TaskUpdated",
        aggregate_id=1,
        payload={"changed_fields": changed_fields},
        occurred_at=FIXED_PAST_INSTANT,
    )
