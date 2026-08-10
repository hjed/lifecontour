"""Task API endpoints.

A task is created *from* a journal, so the creating journal is the path journal
and never a body field — the body says only what the commitment is, when it is
due, and who it involves.

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
``POST /journals/{id}/merge`` already uses — rather than a field on the status
``PATCH``, because it is not a field assignment: it forces the status to *not
done* and writes an intermediate link, so a body able to carry a ``status``
beside a ``due_journal_id`` would have two answers and no rule for picking one.
Its answer includes the task's **intermediate journals**, which is what lets a
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
from core_shared.models.tasks import Task, TaskLinkRole, TaskValidationError
from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.identifiers import DatabaseIdPath
from app.api.common.schemas import JsonApiLinks, get_request_base_url
from app.api.tasks.schemas import (
    JournalTasksResponse,
    TaskAttributes,
    TaskContactLinkRequest,
    TaskCreateRequest,
    TaskIntermediateJournalLinkRequest,
    TaskReadResponse,
    TaskResource,
    TaskResponse,
    TaskRetargetRequest,
    TaskUpdateRequest,
    persisted_task_id,
    task_self_link,
    to_journal_tasks_response,
    to_task_read_resource,
)
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
            text=task.text,
            status=task.status,
            creating_journal_id=task.creating_journal_id,
            due_journal_id=task.due_journal_id,
            intermediate_journal_ids=intermediate_journal_ids,
            created_at=task.created_at,
            updated_at=task.updated_at,
        ),
        links=JsonApiLinks(self=task_self_link(task_id, base_url)),
    )


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
    when it is still not done and its due journal has either passed or been
    cancelled. `lapse_reason` says which, because the two ask you for different
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
    """Change a task's text, its status, or both.

    A task is reached by its own id here rather than through a journal, because
    neither change involves a journal at all: marking a task done or cancelled
    creates no journal link, rewording one infers no link either, and the due
    journal is not re-read on either path — so a *lapsed* task stays both
    completable and editable from wherever the user found it. There is still no
    task **collection** — the specification is explicit that no screen lists
    every task — only this member route.

    Both attributes are optional and at least one must be present, because
    JSON:API sends the attributes that changed. When both arrive they are one
    change: the service applies them under a single read and a single write, so
    a request can never be half-applied.

    Raises:
        400: An unknown status, blank text, an unknown attribute, a body naming
             no change at all, or a body id that disagrees with the path.
        404: The task does not exist or is not yours; the two are the same
             answer by design.
        409: The transition is refused. Only leaving *cancelled* is: a cancelled
             task is reopened by retargeting it onto a new future journal, which
             returns it to not done, and the message says so.
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

    This is how a deadline is extended, and it is the **only** way a cancelled
    or a done task is reopened: retargeting always leaves the task *not done*.
    It is also what a refused status transition tells a caller to do.

    An action sub-resource rather than a field on ``PATCH /api/tasks/{id}``,
    following ``POST /api/journals/{id}/merge``. A retarget is not a field
    assignment — it forces the status and writes a link row — so a body able to
    carry a ``status`` beside a ``due_journal_id`` would have two answers and no
    rule for choosing between them.

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
             is written: not the status, not the anchor, not the link.
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
