"""Task API endpoints.

A task is created *from* a journal, so the creating journal is the path journal
and never a body field — the body says only what the commitment is, when it is
due, and who it involves.

The controller is deliberately thin. Every invariant — both anchors exist and
belong to the acting user, the due journal is future-dated, referenced contacts
exist — lives in ``TaskService.create_task``, which is a ``@transactional`` unit
of work; the status transition matrix likewise lives in
``TaskService.set_status``. This module therefore opens **no** transaction and
catches **no** domain error: the registered ``DomainError`` handler renders each
one with its own status and JSON:API code, so the MCP tool inherits exactly the
same answers.

It *raises* exactly one, and only on the update path: a body whose resource id
disagrees with the path is a JSON:API envelope problem with no domain or MCP
equivalent, so there is nowhere else for it to live.
"""

from core_shared.models.tasks import Task, TaskValidationError
from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.tasks.schemas import (
    TaskAttributes,
    TaskCreateRequest,
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
    journal_id: int,
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
    return TaskResponse(data=_to_resource(created))


@router.patch("/tasks/{task_id}")
@inject
async def update_task(
    task_id: int,
    task_request: TaskUpdateRequest,
    task_service: FromDishka[TaskService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> TaskResponse:
    """Change a task's status.

    A task is reached by its own id here rather than through a journal, because
    changing a status involves no journal at all: marking a task done or
    cancelled creates no journal link and does not re-check the due journal, so
    a *lapsed* task is completable from wherever the user found it. There is
    still no task **collection** — the specification is explicit that no screen
    lists every task — only this member route.

    Raises:
        400: An unknown status, an unknown attribute, or a body id that
             disagrees with the path.
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

    updated = await task_service.set_status(
        user_id=user.id,
        task_id=task_id,
        status=task_request.data.attributes.status,
        transaction=connection,
    )
    return TaskResponse(data=_to_resource(updated))
