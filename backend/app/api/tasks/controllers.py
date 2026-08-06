"""Task API endpoints.

A task is created *from* a journal, so the creating journal is the path journal
and never a body field — the body says only what the commitment is, when it is
due, and who it involves.

The controller is deliberately thin. Every invariant — both anchors exist and
belong to the acting user, the due journal is future-dated, referenced contacts
exist — lives in ``TaskService.create_task``, which is a ``@transactional`` unit
of work. This module therefore opens **no** transaction and catches **no** domain
error: the registered ``DomainError`` handler renders each one with its own
status and JSON:API code, so the MCP tool inherits exactly the same answers.
"""

from core_shared.models.tasks import Task
from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.tasks.schemas import (
    TaskAttributes,
    TaskCreateRequest,
    TaskResource,
    TaskResponse,
)
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.auth.models import SessionUser

router = APIRouter(tags=["tasks"])


def _to_resource(task: Task) -> TaskResource:
    """Render a created task as a JSON:API resource.

    No ``self`` link is emitted: this phase ships no endpoint to read a task
    back, and a link that 404s is worse than an absent one. It arrives with the
    read model.
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
