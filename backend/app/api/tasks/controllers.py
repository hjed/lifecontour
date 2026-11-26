"""Task API endpoints.

A task is created either *from* a journal or *on* a list. From a journal, the
creating journal is the path journal and never a body field — the body says only
what the commitment is, when it is due, and who it involves. On a list, the list
is the path and the task has no creating journal; the body may name the day it
is due or the future journal it is due in.

The controller is deliberately thin. Every invariant — both anchors exist and
belong to the acting user, the due journal is future-dated, referenced contacts
exist — lives in ``TaskService.create_task``, which is a ``@transactional`` unit
of work; the transition matrix and the text rule likewise live in
``TaskService.update_task``, and owner scoping in ``delete_task``. This module
therefore opens **no** transaction and catches **no** domain error: the
registered ``DomainError`` handler renders each one with its own status and
JSON:API code, so the MCP tools inherit exactly the same answers.

It *raises* exactly one, and only on the update path: a body whose resource id
disagrees with the path is a JSON:API envelope problem with no domain or MCP
equivalent, so there is nowhere else for it to live.

The contact-link routes answer **204** rather than the task. There is still no
endpoint that reads a task's contacts back, so echoing the link would be a
second definition of what got linked, sitting beside a read surface that does
not exist. 204 is also what keeps idempotency invisible: a repeat of either call
is indistinguishable from the first, which is the whole of what idempotent
means to a client.

The **retarget** is the exception, and answers with the task. It is an action
sub-resource — ``POST /tasks/{id}/retarget``, the shape
``POST /journals/{id}/merge`` already uses — and the ``PATCH`` carries a
``due_journal_id`` too, under the same rules: on a journal-only task it forces
the status to *not done* and writes an intermediate link, so a ``PATCH`` naming
another ``status`` beside it has two answers and is refused rather than
guessed at. Its answer includes the task's **intermediate journals**, which is what lets a
caller see the journal it just left without a second request. Every route that
returns a task fills the same attribute in — create and the ``PATCH`` as well as
the retarget — so there is one resource type with one attribute set whichever
route produced it, rather than a payload a client has to special-case. While no
read surface exists, these responses are also the only place the trail is
reachable at all.

Those routes call the service's ``*_with_trail`` methods rather than reading the
trail themselves, and that is a correctness matter rather than tidiness: a read
taken *after* the write's unit of work commits can observe a concurrent write on
the same task, and would pair an older ``due_journal_id`` and status with a newer
set of links — a task representation that never existed as one version. The
wrappers put both inside one unit of work. Raised by the pull request's automated
review.
"""

from typing import Annotated

from core_shared.models.history import Provenance
from core_shared.models.tasks import (
    DEFAULT_UPCOMING_DAYS_AHEAD,
    MAX_UPCOMING_DAYS_AHEAD,
    Task,
    TaskLinkRole,
    TaskValidationError,
)
from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.identifiers import DatabaseIdPath
from app.api.common.schemas import (
    JsonApiLinks,
    get_request_base_url,
)
from app.api.history import HistoryListResponse
from app.api.history.pages import (
    HistoryLimitQuery,
    HistoryPageQuery,
    history_offset,
    history_page_response,
)
from app.api.tasks.schemas import (
    JournalTasksResponse,
    ListTaskCreateRequest,
    TaskAttributes,
    TaskCollectionResponse,
    TaskContactLinkRequest,
    TaskCreateRequest,
    TaskIntermediateJournalLinkRequest,
    TaskMoveRequest,
    TaskReadResponse,
    TaskReorderRequest,
    TaskResource,
    TaskResponse,
    TaskRetargetRequest,
    TaskUpdateRequest,
    UpcomingTasksResponse,
    persisted_task_id,
    task_attribute_values,
    task_self_link,
    to_journal_tasks_response,
    to_task_read_resource,
    to_upcoming_tasks_response,
)
from app.core.history.services.task_history_service import TaskHistoryService
from app.core.tasks.services.task_read_service import TaskReadService
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.auth.models import SessionUser

router = APIRouter(tags=["tasks"])


def _to_resource(
    task: Task, intermediate_journal_ids: list[int], base_url: str = ""
) -> TaskResource:
    """Render a task as a JSON:API resource.

    The ``self`` link is emitted now that ``GET /api/tasks/{task_id}`` exists.
    It was deliberately absent while it would have 404ed — a ``PATCH`` target is
    not a ``GET`` target — and it arrives here, with the read model, exactly as
    that omission said it would.

    The trail is a parameter rather than something read here, because a renderer
    that queried would make every caller's cost invisible. Every route that
    returns a task passes one: the resource has a single attribute set whichever
    route produced it, so a client can write one renderer for it. ``base_url``
    travels the same way, so the link is absolute like every other resource's.
    """
    task_id = persisted_task_id(task)
    return TaskResource(
        id=str(task_id),
        attributes=TaskAttributes(
            **task_attribute_values(task, intermediate_journal_ids)
        ),
        links=JsonApiLinks(self=task_self_link(task_id, base_url)),
    )


# Declared **before** ``/tasks/{task_id}``, and that ordering is load-bearing:
# FastAPI matches routes in registration order, so the member route would
# otherwise claim ``upcoming`` as an id and answer 400. The same footgun
# ``main.py`` records for ``/journals/series``, and an integration test pins it.
@router.get("/tasks/upcoming")
@inject
async def list_upcoming_tasks(
    request: Request,
    task_read_service: FromDishka[TaskReadService],
    user: FromDishka[SessionUser],  # Require authentication
    days_ahead: Annotated[
        int,
        Query(
            ge=0,
            le=MAX_UPCOMING_DAYS_AHEAD,
            description="How many days beyond today to include",
        ),
    ] = DEFAULT_UPCOMING_DAYS_AHEAD,
) -> UpcomingTasksResponse:
    """What is coming up: tasks due between today and `days_ahead` days ahead.

    The home dashboard's tasks section. The window defaults to **seven days**
    and both ends are **inclusive**, so a task due today is in it and so is one
    due on the last day.

    **The window is anchored on today in your timezone**, not the server's and
    not the browser's, and each row's due-journal date arrives already resolved
    in that same zone — so a client can render "Today" or "Tomorrow" without
    re-deriving a day and disagreeing with the window it was given.

    Note that this rule and the *future-dated* one a due journal must satisfy
    disagree about today on purpose: a journal must be strictly future-dated to
    *become* a deadline, while a deadline landing today is exactly what this
    listing exists to surface.

    **A journal under way counts as today.** A task due in a multi-day journal
    that has started but not ended is listed, due today: it is not late until
    the journal's last day is over.

    **Done, cancelled and lapsed tasks are absent.** A task lapses when it is
    still not done and its due journal has **ended** — its last day is behind
    you — or been **cancelled**; inside a forward window only the second can
    happen, so a cancelled meeting is what takes a task off this list. Nothing is lost when it does — the task stays on
    every journal it is linked to, where `GET /api/journals/{journal_id}/tasks`
    lists it with its lapse marker and the user can **retarget** it onto a new
    future journal.

    **Tasks on a list are absent too**, even one due in a journal inside the
    window: this listing is journal-only for now.

    **The whole window is returned and it is not paginated.** The window bounds
    the collection, so a caller showing the first few can name the full count
    from `meta.total` and reveal the rest without asking again. There is
    deliberately no unpaginated *unbounded* listing: `days_ahead` is capped, and
    this endpoint must not become the "every task" collection no screen has.

    No transaction is opened on this path.

    Raises:
        400: `days_ahead` below zero or above the maximum.
    """
    upcoming = await task_read_service.read_models_for_upcoming_window(
        user.id, days_ahead=days_ahead
    )
    return to_upcoming_tasks_response(upcoming, get_request_base_url(request))


@router.get("/tasks/{task_id}")
@inject
async def get_task(
    task_id: DatabaseIdPath,
    request: Request,
    task_read_service: FromDishka[TaskReadService],
    user: FromDishka[SessionUser],  # Require authentication
) -> TaskReadResponse:
    """Read one task whole: its journals by role, its contacts, and its lapse.

    This is the first route that reads a task back. Every write response has
    carried the journal trail as bare ids because there was nowhere to resolve
    them; here each journal arrives with its title and its date — a **date**,
    already in your timezone, so a client cannot re-derive it in the browser's
    zone and disagree with the rule that judged the task.

    **`lapsed` is derived on every read and never stored.** A task is lapsed
    when it is still not done and its due journal has either ended (its last
    day is behind you, so a task due in a trip under way is not lapsed) or been
    cancelled. Only a task with no list lapses: a task on a list never does,
    and may also have no journal in either role, in which case that id and ref
    are null. `lapse_reason` says which, because the two ask you for different
    things: a passed date invites retargeting the task onto a new future
    journal, while a cancelled meeting may mean the commitment is moot. Only the
    due journal decides it — the journal a task arose in is almost always in the
    past.

    A lapsed task is not invalid and stays fully editable: it can be completed,
    reworded, cancelled, or **retargeted** onto a new future journal, which is
    how it is resurrected.

    No transaction is opened on this path.

    Raises:
        400: A path id that is not an integer, or one outside the range an
             ``INTEGER`` column can hold.
        404: The task does not exist or is not yours; the two are the same
             answer by design, so a 404 here never means "it was deleted".
    """
    model = await task_read_service.read_model(user.id, task_id)
    return TaskReadResponse(
        data=to_task_read_resource(model, get_request_base_url(request))
    )


@router.get("/tasks/{task_id}/history")
@inject
async def get_task_history(
    task_id: DatabaseIdPath,
    request: Request,
    history_service: FromDishka[TaskHistoryService],
    user: FromDishka[SessionUser],  # Require authentication
    page: HistoryPageQuery = 1,
    limit: HistoryLimitQuery = 20,
) -> HistoryListResponse:
    """Get field-level change history for a task.

    Returns a paginated JSON:API list of history entries, most recent first,
    covering everything a task's events announce: its creation, rewords, status
    moves, retargets, the journals it has been linked to and the people on it.
    Each entry carries its provenance and its actor, in the same shape the
    journal and contact feeds use, so one component renders all three.

    History is produced asynchronously by the projection consumer, so a
    just-made change may take a moment to appear — and a task created moments
    ago answers an empty list rather than a 404, because "not projected yet" is
    not "does not exist".

    **A deleted task's history is still readable**, which is what this route
    exists for. Tasks are hard-deleted, so unlike every other history read this
    one cannot authorise by loading the aggregate; ownership is carried on the
    history rows themselves and resolved by ``TaskHistoryService``, with the
    live task row only as a fallback for the window before projection catches
    up. Nothing here re-implements that check, so this endpoint and the
    ``get_task_history`` MCP tool cannot answer it differently.

    This is a **record**, not a working surface. It is scoped to one task by its
    id and there is no collection beside it, in keeping with the specification's
    rule that tasks are worked with in exactly two places.

    No transaction is opened on this path.

    A page past the end of the history is an ordinary empty answer, not an
    error; ``meta`` still carries the total, so a client that overshot can find
    its way back.

    Raises:
        400: A path id that is not an integer, or one outside the range an
             ``INTEGER`` column can hold; a ``limit`` above 100; or a ``page``
             outside the ``INTEGER`` range. The last is bounded because ``page``
             reaches SQL as ``(page - 1) * limit``, bound to PostgreSQL's
             ``OFFSET`` as a bigint — unbounded, a legal-looking request could
             overflow it and answer with a database error rather than anything
             the client could act on.
        404: The task does not exist, is not yours, or was deleted without ever
             leaving history behind. As on every other task route the three are
             one answer, so a rejection cannot be used to probe for other users'
             tasks.
    """
    history_entries = await history_service.get_task_history(
        task_id=task_id,
        user_id=user.id,
        limit=limit,
        offset=history_offset(page, limit),
    )
    total_count = await history_service.get_task_history_count(
        task_id=task_id,
        user_id=user.id,
    )

    return history_page_response(
        history_entries,
        total_count=total_count,
        resource_type="task_history",
        self_url=f"{get_request_base_url(request)}/api/tasks/{task_id}/history",
        page=page,
        limit=limit,
    )


@router.get("/journals/{journal_id}/tasks")
@inject
async def list_journal_tasks(
    journal_id: DatabaseIdPath,
    request: Request,
    task_read_service: FromDishka[TaskReadService],
    user: FromDishka[SessionUser],  # Require authentication
    role: Annotated[
        TaskLinkRole | None,
        Query(description="Return only tasks holding this role in the journal"),
    ] = None,
) -> JournalTasksResponse:
    """List a journal's tasks, grouped by the role each link holds.

    A journal shows three groups: tasks **due** here, tasks **created** here,
    and tasks **mentioned** here through an intermediate link. A task may hold
    **more than one group** — the same journal can be both its anchors, and
    retargeting onto a journal it already mentioned leaves that mention in
    place — so it appears **once** in `data`, carrying in `link_roles` every
    role it holds among the groups returned, with the grouping itself in
    `meta.groups`. JSON:API forbids the same resource twice in `data`, which is
    why the roles are an attribute rather than the structure. Under a `role`
    filter `link_roles` narrows with the groups, so it never names a group that
    `meta.groups` reports as empty.

    **Every linked task is listed, in every status.** Done, cancelled and lapsed
    tasks all appear: a journal is where a lapsed task is meant to be found
    again, and a done task's link to the journal it arose in is part of the
    record. Lapsed ones carry the marker and the reason rather than being
    filtered out. (The home dashboard's task section is the surface that hides
    them.)

    Rows are ordered by due-journal date, soonest first, with ties broken by
    task id. In the *due* group every task shares this journal's date, so that
    group is ordered by id.

    Unpaginated by design: a journal's tasks are bounded by the journal.

    Raises:
        400: A path id that is not an integer, one outside the range an
             ``INTEGER`` column can hold, or an unknown `role`.
        404: The journal does not exist or is not yours; the two are the same
             answer, so a rejection cannot be used to probe for other users'
             journals. A journal of yours with nothing linked to it answers 200
             with three empty groups.
    """
    groups = await task_read_service.read_models_for_journal(
        user.id, journal_id, role=role
    )
    return to_journal_tasks_response(groups, get_request_base_url(request))


@router.post("/journals/{journal_id}/tasks", status_code=status.HTTP_201_CREATED)
@inject
async def create_task(
    journal_id: DatabaseIdPath,
    task_request: TaskCreateRequest,
    request: Request,
    task_service: FromDishka[TaskService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> TaskResponse:
    """Create a task in the journal it arose from.

    The path journal is the task's *creating* journal. The body names the
    journal it is **due** in, which must be an existing journal of yours dated
    after today in your timezone.

    Raises:
        400: Empty text, an unknown attribute, or a due journal that is not
             future-dated (the message carries both dates).
        404: Either journal anchor does not exist or is not yours — the message
             names which anchor, but never whether it was absent or somebody
             else's — or a referenced contact does not exist.
    """
    attributes = task_request.data.attributes
    # The trail is read inside the write's unit of work rather than after it, so
    # the task and its links in the response are one consistent snapshot. Empty
    # in practice on this path — creation writes no intermediate link — but read
    # rather than assumed, so the field has one definition across every surface.
    #
    # The provenance the service records on the ``TaskCreated`` event is passed
    # explicitly because the service defaults to ``SYSTEM``: an endpoint that
    # said nothing would file every change a person made in the browser under
    # "system" in their own history, and nothing above the outbox row would show
    # it.
    created, trail = await task_service.create_task_with_trail(
        user_id=user.id,
        creating_journal_id=journal_id,
        due_journal_id=attributes.due_journal_id,
        text=attributes.text,
        transaction=connection,
        contact_ids=attributes.contact_ids,
        source=Provenance.UI,
        changed_by="ui",
    )
    return TaskResponse(
        data=_to_resource(created, trail, get_request_base_url(request))
    )


@router.post("/task-lists/{list_id}/tasks", status_code=status.HTTP_201_CREATED)
@inject
async def create_list_task(
    list_id: DatabaseIdPath,
    task_request: ListTaskCreateRequest,
    request: Request,
    task_service: FromDishka[TaskService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> TaskResponse:
    """Create a task at the bottom of one of your lists.

    The task has no creating journal. The body says what it is, optionally when
    it is due — a day, today or later in your timezone, or a journal of yours
    dated in the future, never both — and who it involves.

    Raises:
        400: Empty text, an unknown attribute (a creating journal included), a
             due date that is not a ``YYYY-MM-DD`` string, a due date before
             today (``TASK_DUE_DATE_IN_PAST``, naming both days), a due journal
             not in the future (``TASK_DUE_JOURNAL_NOT_FUTURE``, naming both
             days), or both a due date and a due journal
             (``TASK_VALIDATION_ERROR``, ``meta.field`` = ``due_date``).
        404: The list does not exist or is not yours; the due journal does not
             exist or is not yours (``TASK_ANCHOR_JOURNAL_NOT_FOUND``,
             ``meta.anchor`` = ``due``); or a referenced contact does not exist.
        409: The list is archived (``TASK_LIST_ARCHIVED``); unarchive it first.
    """
    attributes = task_request.data.attributes
    created, trail = await task_service.create_list_task_with_trail(
        user_id=user.id,
        task_list_id=list_id,
        text=attributes.text,
        transaction=connection,
        due_date=attributes.due_date,
        due_journal_id=attributes.due_journal_id,
        contact_ids=attributes.contact_ids,
        source=Provenance.UI,
        changed_by="ui",
    )
    return TaskResponse(
        data=_to_resource(created, trail, get_request_base_url(request))
    )


@router.patch("/tasks/{task_id}")
@inject
async def update_task(
    task_id: DatabaseIdPath,
    task_request: TaskUpdateRequest,
    request: Request,
    task_service: FromDishka[TaskService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> TaskResponse:
    """Change a task's text, status, flag, icon or dates — any of them, in one write.

    A task is reached by its own id here rather than through a journal: marking
    a task done or cancelled creates no journal link, rewording one infers no
    link either, and the due journal is not re-read unless a date is being set
    — so a *lapsed* task stays both completable and editable from wherever the
    user found it. There is still no
    task **collection** — the specification is explicit that no screen lists
    every task — only this member route.

    Every attribute is optional and at least one must be present, because
    JSON:API sends the attributes that changed. When several arrive they are one
    change: the service applies them under a single read and a single write, so
    a request can never be half-applied.

    The flag and the icon apply to **every** task, journal-only ones included,
    in any status. ``"icon": null`` clears the icon; an absent ``icon`` leaves
    it alone.

    A **task on a list** takes a ``due_date`` the same way: a ``YYYY-MM-DD``
    day sets or changes it, ``null`` clears it, and the status is kept — a
    plain edit, with no acknowledgement. A day that is set must be today or
    later in the user's timezone; resending the one it has changes nothing.
    Setting one on a task due in a journal replaces the journal, which is kept
    as an intermediate journal.

    Every task takes a ``due_journal_id``, which must be one of the user's
    journals dated after today; the journal it leaves is kept as an
    intermediate journal. On a **list task** it is a plain edit like the date:
    ``null`` clears it, a due date is replaced, and the status is kept. On a
    **journal-only task** it is a retarget, as ``POST .../retarget`` is: the
    task becomes not done — a done one only with ``acknowledge_reopen`` or
    ``"status": "not_done"`` — and it cannot be cleared.

    Raises:
        400: An unknown status, blank text, an unknown attribute, a null or
             non-boolean flag, an icon outside the fixed set, a due date that
             is not a ``YYYY-MM-DD`` string, is before today
             (``TASK_DUE_DATE_IN_PAST``) or is set on a task not on a list or
             beside a ``due_journal_id`` (``meta.field`` = ``due_date``), a due
             journal that is not future-dated (``TASK_DUE_JOURNAL_NOT_FUTURE``),
             a journal-only task's due journal cleared (``meta.field`` =
             ``due_journal_id``) or moved beside a status other than
             ``not_done`` (``meta.field`` = ``status``), a non-integer journal
             id or a non-boolean ``acknowledge_reopen``, a body naming no
             change at all, or a body id that disagrees with the path.
        404: The task does not exist or is not yours, or the due journal does
             not exist or is not yours (``TASK_ANCHOR_JOURNAL_NOT_FOUND``); in
             each case the two are the same answer by design.
        409: The transition is refused. Only a journal-only task leaving
             *cancelled* is: it is reopened by moving it onto a new future
             journal, which returns it to not done, and the message says so. A
             task on a list is never refused — a done or cancelled list task is
             reopened directly by sending ``"status": "not_done"`` here. Or a
             done journal-only task's due journal is moved without the
             acknowledgement (``TASK_REOPEN_NOT_ACKNOWLEDGED``). Or the task's
             list is archived (``TASK_LIST_ARCHIVED``).
    """
    # The only thing this controller decides. It is a transport concern — which
    # of two places names the resource — rather than a domain rule, so it has no
    # MCP counterpart (a tool takes the id once) and no place in the service.
    # Preferring the path silently would let a client PATCH a task it believes
    # it is not touching.
    if task_request.data.id != str(task_id):
        raise TaskValidationError(
            "id",
            f"The body's task id ({task_request.data.id}) must match the path "
            f"({task_id})",
        )

    attributes = task_request.data.attributes
    updated, trail = await task_service.update_task_with_trail(
        user_id=user.id,
        task_id=task_id,
        text=attributes.text,
        status=attributes.status,
        flagged=attributes.flagged,
        icon=attributes.icon_change(),
        due_date=attributes.due_date_change(),
        due_journal_id=attributes.due_journal_id_change(),
        acknowledge_reopen=attributes.acknowledge_reopen,
        transaction=connection,
        source=Provenance.UI,
        changed_by="ui",
    )
    return TaskResponse(
        data=_to_resource(updated, trail, get_request_base_url(request))
    )


@router.post("/tasks/{task_id}/retarget")
@inject
async def retarget_task(
    task_id: DatabaseIdPath,
    retarget_request: TaskRetargetRequest,
    request: Request,
    task_service: FromDishka[TaskService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> TaskResponse:
    """Move a task onto a new due journal, keeping the one it is leaving.

    This is how a deadline is extended, and how a cancelled journal-only task is
    reopened: retargeting a journal-only task always leaves it *not done*. It
    is also what a refused status transition tells a caller to do. A **task on
    a list** keeps its status: its due journal is a plain date, so a done or
    cancelled one moves and stays closed, with no acknowledgement, and an
    undated or dated one is given the journal. ``PATCH /api/tasks/{id}`` with a
    ``due_journal_id`` applies the same rules.

    An action sub-resource, following ``POST /api/journals/{id}/merge``, with
    no ``status`` in its body: a journal-only task's retarget forces the status,
    so a status beside it would be a second answer.

    The response carries the task **and its intermediate journals**, including
    the one it has just left, so the trail is visible without a second request.
    Asking for the journal the task is already due in is a no-op: nothing is
    set, so nothing is validated, nothing is written and no acknowledgement is
    needed.

    Raises:
        400: A due journal that is not future-dated (the message carries both
             dates), an unknown attribute, a body declaring another resource
             type, or an id outside the range an ``INTEGER`` column can hold.
        404: The task does not exist or is not yours, or the new due journal
             does not exist or is not yours — in both cases the two are the same
             answer by design.
        409: The task is *done* and the reopen was not acknowledged. Its own
             code, ``TASK_REOPEN_NOT_ACKNOWLEDGED``, so a surface can offer
             "reopen it anyway" rather than showing a generic failure. Nothing
             is written: not the status, not the anchor, not the link. A task
             on a list is never asked for it. Or the task's list is archived
             (``TASK_LIST_ARCHIVED``).
    """
    attributes = retarget_request.data.attributes
    retargeted, trail = await task_service.retarget_due_journal_with_trail(
        user_id=user.id,
        task_id=task_id,
        due_journal_id=attributes.due_journal_id,
        transaction=connection,
        acknowledge_reopen=attributes.acknowledge_reopen,
        source=Provenance.UI,
        changed_by="ui",
    )
    return TaskResponse(
        data=_to_resource(retargeted, trail, get_request_base_url(request))
    )


@router.post("/tasks/{task_id}/reorder")
@inject
async def reorder_task(
    task_id: DatabaseIdPath,
    reorder_request: TaskReorderRequest,
    request: Request,
    task_service: FromDishka[TaskService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> TaskCollectionResponse:
    """Move an open task on a list to the top, or just after another open task.

    The list page's drag and keyboard move. ``after_task_id`` names the open
    task on the same list it should follow, or is ``null`` for the top. One move
    changes other tasks' positions too, so the answer is the list's open tasks
    in their new order. Reordering records no history.

    Raises:
        400: The task is on no list or is closed; the anchor is the task itself,
             closed or on another list (``TASK_VALIDATION_ERROR`` with
             ``meta.field``); or a malformed body or an out-of-range id.
        404: The task or the anchor does not exist or is not yours —
             indistinguishably.
        409: The list is archived (``TASK_LIST_ARCHIVED``), or a task closed or
             left the list while the move waited (``TASK_LIST_CHANGED``): read
             the list again and retry.
    """
    reordered = await task_service.reorder_task(
        user_id=user.id,
        task_id=task_id,
        after_task_id=reorder_request.data.attributes.after_task_id,
        transaction=connection,
    )
    base_url = get_request_base_url(request)
    return TaskCollectionResponse(
        data=[_to_resource(task, trail, base_url) for task, trail in reordered]
    )


@router.post("/tasks/{task_id}/move")
@inject
async def move_task_to_list(
    task_id: DatabaseIdPath,
    move_request: TaskMoveRequest,
    request: Request,
    task_service: FromDishka[TaskService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> TaskResponse:
    """Move a task onto one of your lists, or from one list to another.

    The task joins the **bottom** of the list. A journal-only task added to a
    list keeps its journals and due journal and **stops lapsing**: past its date
    it reads as overdue on the list instead. A list task moved to another list
    keeps its due date or due journal. Status, flag, icon and contacts are kept
    either way, and a task in any status may move.

    An action sub-resource, as the retarget is: a move repositions the task, so
    it is not a field on ``PATCH``. Moving a task to the list it is already on
    is a no-op — nothing changes and no history is written; reorder within a
    list instead. The response is the task with its intermediate journals.

    Raises:
        400: A body of another type, an unknown attribute, or a ``task_list_id``
             that is not a JSON integer within an ``INTEGER`` column's range
             (``null`` included: leaving a list is not a move).
        404: ``TASK_NOT_FOUND`` when the task does not exist or is not yours;
             ``TASK_LIST_NOT_FOUND`` when the list does not exist or is not
             yours. Each pair is one answer by design.
        409: ``TASK_LIST_ARCHIVED`` when the task's current list is archived
             (named first), or else when the target list is;
             ``TASK_LIST_CHANGED`` when the task moved to another list while
             the move waited — read it again and retry. Nothing is written.
    """
    moved, trail = await task_service.move_to_list_with_trail(
        user_id=user.id,
        task_id=task_id,
        task_list_id=move_request.data.attributes.task_list_id,
        transaction=connection,
        source=Provenance.UI,
        changed_by="ui",
    )
    return TaskResponse(data=_to_resource(moved, trail, get_request_base_url(request)))


@router.post("/tasks/{task_id}/remove-from-list")
@inject
async def remove_task_from_list(
    task_id: DatabaseIdPath,
    request: Request,
    task_service: FromDishka[TaskService],
    task_read_service: FromDishka[TaskReadService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> TaskReadResponse:
    """Take a task off its list, making it a journal-only task. No body.

    Only a task holding **both** a creating journal and a due journal may
    leave: a journal-only task lives between the two. A task without both
    cannot be removed — move it to another list, cancel it or delete it
    instead. The task keeps its journals, status, flag, icon and contacts.

    **The answer says whether the task is now lapsed.** Off its list it
    follows the journal-only rule again, so a task whose due journal has
    passed (or been cancelled) is lapsed the moment it leaves. The response is
    the task read model ``GET /api/tasks/{task_id}`` answers, with ``lapsed``
    and ``lapse_reason``, read once the removal has committed.

    Removing a task that is on no list is a no-op — nothing changes and no
    history is written. An action sub-resource, as ``/move`` is: leaving a list
    is not a move, so ``/move`` refuses a null list.

    Raises:
        400: A path id that is not an integer, or one outside the range an
             ``INTEGER`` column can hold.
        404: ``TASK_NOT_FOUND`` when the task does not exist or is not yours;
             the two are the same answer by design.
        409: ``TASK_LIST_ARCHIVED`` when its list is archived (checked first);
             ``TASK_LIST_CHANGED`` when the task left its list while the
             removal waited — read it again and retry;
             ``TASK_LIST_REMOVAL_NEEDS_JOURNALS`` when it lacks a creating or a
             due journal. Nothing is written.
    """
    await task_service.remove_from_list(
        user_id=user.id,
        task_id=task_id,
        transaction=connection,
        source=Provenance.UI,
        changed_by="ui",
    )
    model = await task_read_service.read_model(user.id, task_id)
    return TaskReadResponse(
        data=to_task_read_resource(model, get_request_base_url(request))
    )


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_task(
    task_id: DatabaseIdPath,
    task_service: FromDishka[TaskService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """Delete a task permanently. Prefer cancelling it.

    **Cancelling is the ordinary action and this is the exception**, matching
    the stance the journals specification takes on event journals. A cancelled
    task stays part of the record of what the user committed to and can be
    reopened by retargeting it onto a new future journal; a deleted one is gone.
    Use `PATCH /api/tasks/{task_id}` with `status: "cancelled"` unless the task
    was a genuine mistake — a duplicate, or something typed into the wrong
    place.

    The task's intermediate-journal and contact links go with it. The journals
    and contacts themselves are untouched, including both anchors: deleting the
    task is the supported way to unblock a journal deletion that a task was
    holding up, not a reason to lose the journal as well.

    Answers 204 with no body: there is no resource left to return.

    Raises:
        400: A path id that is not an integer, or one outside the range an
             ``INTEGER`` column can hold.
        404: The task does not exist or is not yours; the two are the same
             answer by design. A second delete of the same task answers 404 too,
             because reporting success for a task that was not there would tell
             a client a commitment is gone when it may still be on a journal.
    """
    await task_service.delete_task(
        user_id=user.id,
        task_id=task_id,
        transaction=connection,
        source=Provenance.UI,
        changed_by="ui",
    )


@router.post(
    "/tasks/{task_id}/relationships/contacts",
    status_code=status.HTTP_204_NO_CONTENT,
)
@inject
async def link_task_contact(
    task_id: DatabaseIdPath,
    link_request: TaskContactLinkRequest,
    task_service: FromDishka[TaskService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """Link a contact to a task.

    A task-contact link is a plain reference: it carries no relationship type,
    no role and no attendance status, so the body names a contact and nothing
    else. Contact links are editable in **any** status — a done or cancelled
    task takes one exactly as an open one does.

    Linking a contact that is already linked succeeds and changes nothing. The
    answer is 204 either way, deliberately: an idempotent operation that looked
    different on a retry would not be one.

    Raises:
        400: An unknown field, a relationship attribute, a body declaring
             another resource type, or an id that is not an integer.
        404: The task does not exist or is not yours — the two are the same
             answer by design — or the contact does not exist.
    """
    await task_service.link_contact(
        user_id=user.id,
        task_id=task_id,
        contact_id=link_request.data.contact_id,
        transaction=connection,
        source=Provenance.UI,
        changed_by="ui",
    )


@router.delete(
    "/tasks/{task_id}/relationships/contacts/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@inject
async def unlink_task_contact(
    task_id: DatabaseIdPath,
    contact_id: DatabaseIdPath,
    task_service: FromDishka[TaskService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """Remove a contact link from a task.

    Idempotent, and deliberately **not** conditional on the contact still
    existing: ``task_contacts`` cascades from the contact side, so a deleted
    contact's links are already gone, and 404-ing here would fail the one call a
    user reaches for while tidying up.

    Raises:
        400: A path id that is not an integer, or one outside the range an
             ``INTEGER`` column can hold. FastAPI raises these as validation
             errors and the application-wide handler renders every one of those
             as 400 — an earlier draft of this docstring said 422, which is
             FastAPI's default and not what a client of *this* application ever
             sees.
        404: The task does not exist or is not yours.
    """
    await task_service.unlink_contact(
        user_id=user.id,
        task_id=task_id,
        contact_id=contact_id,
        transaction=connection,
        source=Provenance.UI,
        changed_by="ui",
    )


@router.post(
    "/tasks/{task_id}/relationships/intermediate-journals",
    status_code=status.HTTP_204_NO_CONTENT,
)
@inject
async def attach_task_intermediate_journal(
    task_id: DatabaseIdPath,
    link_request: TaskIntermediateJournalLinkRequest,
    task_service: FromDishka[TaskService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """Attach a journal to a task as an intermediate journal.

    An intermediate journal is one the task was discussed, revisited or
    previously due in. **The relationship is named for the role**, not for the
    resource: a task has three journal relationships and this route manipulates
    only one of them, so calling it ``/journals`` would promise a route that can
    set an anchor. The body's resource ``type`` is still ``journals``, because
    that is what the identifier points at.

    Attaching a journal that is already attached succeeds and changes nothing;
    the answer is 204 either way, which is what makes the operation's idempotency
    invisible to the client.

    Raises:
        400: An unknown field, a role attribute, a body declaring another
             resource type, or an id that is not an integer within an
             ``INTEGER`` column's range.
        404: The task does not exist or is not yours — the two are the same
             answer by design — or the journal does not exist or is not yours,
             which are likewise one answer.
        409: The journal is already the task's creating or due journal. It is
             linked in a role this relationship cannot express: the creating
             journal never changes, and the due journal is changed by
             retargeting.
    """
    await task_service.attach_intermediate_journal(
        user_id=user.id,
        task_id=task_id,
        journal_id=link_request.data.journal_id,
        transaction=connection,
        source=Provenance.UI,
        changed_by="ui",
    )


@router.delete(
    "/tasks/{task_id}/relationships/intermediate-journals/{journal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@inject
async def detach_task_intermediate_journal(
    task_id: DatabaseIdPath,
    journal_id: DatabaseIdPath,
    task_service: FromDishka[TaskService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """Remove an intermediate-journal link from a task.

    Idempotent for every journal but one, and deliberately **not** conditional on
    the journal still existing: ``task_intermediate_journals`` cascades from the
    journal side, so a deleted journal's links are already gone, and 404-ing here
    would fail the one call a user reaches for while tidying up. Deleting a
    journal that is only an intermediate link is permitted, which is what makes
    that state reachable.

    **The exception is a journal that is both an anchor and an intermediate
    journal.** It answers 204 the first time and 409 the second, because once the
    link row is gone this route can no longer tell a retry from a request to
    unlink the task's due journal. A client retrying after a timeout on that one
    shape can therefore see a 409 for a call that already succeeded.

    Raises:
        400: A path id that is not an integer, or one outside the range an
             ``INTEGER`` column can hold.
        404: The task does not exist or is not yours.
        409: The journal is the task's creating or due journal **and** holds no
             intermediate link, so there is nothing to remove — replacing the
             due journal is a retarget, and the creating journal never changes.
             Answered explicitly rather than as a silent success, which would
             read as "it was not attached". A journal that is both an anchor and
             an intermediate journal keeps its link removable.
    """
    await task_service.detach_intermediate_journal(
        user_id=user.id,
        task_id=task_id,
        journal_id=journal_id,
        transaction=connection,
        source=Provenance.UI,
        changed_by="ui",
    )
