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
returns a task fills the same attribute in — create and the status ``PATCH`` as
well as the retarget — so there is one resource type with one attribute set
whichever route produced it, rather than a payload a client has to special-case.
While no read surface exists, these responses are also the only place the trail
is reachable at all.
"""

from core_shared.models.tasks import Task, TaskNotFoundError, TaskValidationError
from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.identifiers import DatabaseIdPath
from app.api.tasks.schemas import (
    TaskAttributes,
    TaskContactLinkRequest,
    TaskCreateRequest,
    TaskResource,
    TaskResponse,
    TaskRetargetRequest,
    TaskUpdateRequest,
)
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.auth.models import SessionUser

router = APIRouter(tags=["tasks"])


def _to_resource(task: Task, intermediate_journal_ids: list[int]) -> TaskResource:
    """Render a task as a JSON:API resource.

    No ``self`` link is emitted: there is still no endpoint to *read* a task
    back — a ``PATCH`` target is not a ``GET`` target — and a link that 404s is
    worse than an absent one. It arrives with the read model.

    The trail is a parameter rather than something read here, because a renderer
    that queried would make every caller's cost invisible. Every route that
    returns a task passes one: the resource has a single attribute set whichever
    route produced it, so a client can write one renderer for it.
    """
    return TaskResource(
        id=str(task.id),
        attributes=TaskAttributes(
            text=task.text,
            status=task.status,
            creating_journal_id=task.creating_journal_id,
            due_journal_id=task.due_journal_id,
            intermediate_journal_ids=intermediate_journal_ids,
            created_at=task.created_at,
            updated_at=task.updated_at,
        ),
    )


async def _trail_of(task: Task, task_service: TaskService, user_id: str) -> list[int]:
    """The journals ``task`` has passed through, for the response body.

    A plain read, run after the write's unit of work has committed, so what it
    reports is what a client would see if it asked again — which is the point of
    including it: the caller sees the trail without a second request.

    **A task that vanishes in that window reads as an empty trail, not a 404.**
    The write has already committed, so answering "not found" would report a
    successful mutation as a failure — the same class of mistake ``_save``
    exists to prevent on the write side, and the window here is wider because
    it straddles a commit. Empty is not a fallback but the literal truth:
    ``task_intermediate_journals`` cascades from ``task_id``, so a task that is
    gone has no links left to list. The window is **reachable**:
    ``DELETE /api/tasks/{task_id}`` in this same module can remove the task
    between the commit and this read.
    """
    if task.id is None:  # pragma: no cover - a persisted task always has one
        return []
    try:
        return await task_service.list_intermediate_journal_ids(
            user_id=user_id, task_id=task.id
        )
    except TaskNotFoundError:
        return []


@router.post("/journals/{journal_id}/tasks", status_code=status.HTTP_201_CREATED)
@inject
async def create_task(
    journal_id: DatabaseIdPath,
    task_request: TaskCreateRequest,
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
    created = await task_service.create_task(
        user_id=user.id,
        creating_journal_id=journal_id,
        due_journal_id=attributes.due_journal_id,
        text=attributes.text,
        transaction=connection,
        contact_ids=attributes.contact_ids,
    )
    # Read rather than assumed empty. Creation writes no intermediate link, so
    # the answer is always ``[]`` today — but a renderer that hardcoded it here
    # and queried on the other routes would be two definitions of one field,
    # and the first to drift would be this one.
    return TaskResponse(
        data=_to_resource(created, await _trail_of(created, task_service, user.id))
    )


@router.patch("/tasks/{task_id}")
@inject
async def update_task(
    task_id: DatabaseIdPath,
    task_request: TaskUpdateRequest,
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
    updated = await task_service.update_task(
        user_id=user.id,
        task_id=task_id,
        text=attributes.text,
        status=attributes.status,
        transaction=connection,
    )
    return TaskResponse(
        data=_to_resource(updated, await _trail_of(updated, task_service, user.id))
    )


@router.post("/tasks/{task_id}/retarget")
@inject
async def retarget_task(
    task_id: DatabaseIdPath,
    retarget_request: TaskRetargetRequest,
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
    retargeted = await task_service.retarget_due_journal(
        user_id=user.id,
        task_id=task_id,
        due_journal_id=attributes.due_journal_id,
        transaction=connection,
        acknowledge_reopen=attributes.acknowledge_reopen,
    )
    return TaskResponse(
        data=_to_resource(
            retargeted, await _trail_of(retargeted, task_service, user.id)
        )
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
        user_id=user.id, task_id=task_id, transaction=connection
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
