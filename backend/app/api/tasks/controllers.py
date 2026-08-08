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
"""

from core_shared.models.history import Provenance
from core_shared.models.tasks import Task, TaskValidationError
from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.identifiers import DatabaseIdPath
from app.api.tasks.schemas import (
    TaskAttributes,
    TaskContactLinkRequest,
    TaskCreateRequest,
    TaskIntermediateJournalLinkRequest,
    TaskResource,
    TaskResponse,
    TaskUpdateRequest,
)
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.auth.models import SessionUser

router = APIRouter(tags=["tasks"])


def _to_resource(task: Task) -> TaskResource:
    """Render a task as a JSON:API resource.

    No ``self`` link is emitted: there is still no endpoint to *read* a task
    back — a ``PATCH`` target is not a ``GET`` target — and a link that 404s is
    worse than an absent one. It arrives with the read model.
    """
    return TaskResource(
        id=str(task.id),
        attributes=TaskAttributes(
            text=task.text,
            status=task.status,
            creating_journal_id=task.creating_journal_id,
            due_journal_id=task.due_journal_id,
            created_at=task.created_at,
            updated_at=task.updated_at,
        ),
    )


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
    # The provenance the service records on the ``TaskCreated`` event. Passed
    # explicitly because the service defaults to ``SYSTEM``: an endpoint that
    # said nothing would file every change a person made in the browser under
    # "system" in their own history, and nothing above the outbox row would show
    # it.
    created = await task_service.create_task(
        user_id=user.id,
        creating_journal_id=journal_id,
        due_journal_id=attributes.due_journal_id,
        text=attributes.text,
        transaction=connection,
        contact_ids=attributes.contact_ids,
        source=Provenance.UI,
        changed_by="ui",
    )
    return TaskResponse(data=_to_resource(created))


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
    return TaskResponse(data=_to_resource(updated))


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

    Idempotent, and deliberately **not** conditional on the journal still
    existing: ``task_intermediate_journals`` cascades from the journal side, so a
    deleted journal's links are already gone, and 404-ing here would fail the one
    call a user reaches for while tidying up. Deleting a journal that is only an
    intermediate link is permitted, which is what makes that state reachable.

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
    )
