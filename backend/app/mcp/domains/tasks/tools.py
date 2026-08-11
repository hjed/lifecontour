"""Tasks domain MCP tools.

A task is a short commitment anchored to two of the user's journals: the one it
arose in, and the future-dated one where it matters. Both anchors are the tool's
arguments because an AI client has no path to take the first from, unlike the
REST surface.

The tools are controller-equivalent and stay that way: they open **no**
transaction and enforce **no** invariant of their own. Every rule — both anchors
exist and are the acting user's, the due journal is future-dated at the moment
it is set, referenced contacts exist, and the status transition is one the
lifecycle permits — belongs to ``TaskService``, which owns the commit. That is
what makes the answers here identical to the endpoint's rather than merely
similar.

**No parameter sets "now".** The service takes one so a test can stand either
side of a local midnight; exposing it would make the future-dated rule opt-out
for any caller, so it is absent here and the transport rejects it as an unknown
argument.
"""

import json
from typing import Annotated, Any

from core_shared.models.history import Provenance
from core_shared.models.tasks import (
    JournalTaskGroups,
    Task,
    TaskJournalRef,
    TaskLinkRole,
    TaskReadModel,
    TaskStatus,
)
from fastmcp import FastMCP
from pydantic import Field, StrictBool
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.identifiers import INT32_MAX
from app.core.tasks.services.task_read_service import TaskReadService
from app.core.tasks.services.task_service import TaskService
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_task_read_service,
    get_task_service,
    mcp_depends,
)


def _link_to_dict(
    task_id: int, contact_id: int, *, linked: bool, changed: bool
) -> dict[str, Any]:
    """The answer both link tools give.

    ``linked`` is the *resulting state* and ``changed`` says whether this call
    moved a row. Both are needed because the operations are idempotent: without
    ``changed`` an agent could not tell a fresh link from a no-op, and without
    ``linked`` it would have to infer the state from which tool it called. There
    is no read tool yet to ask instead.
    """
    return {
        "task_id": task_id,
        "contact_id": contact_id,
        "linked": linked,
        "changed": changed,
    }


def _journal_link_to_dict(
    task_id: int, journal_id: int, *, attached: bool, changed: bool
) -> dict[str, Any]:
    """The answer both intermediate-journal tools give.

    ``attached`` is the *resulting state* and ``changed`` says whether this call
    moved a row, for the reason the contact tools carry the same pair: the
    operations are idempotent, so without ``changed`` an agent could not tell a
    fresh link from a no-op, and without ``attached`` it would have to infer the
    state from which tool it called.

    **These two tools return the pair rather than the task**, which the
    task-returning tools now carry a trail on. Answering with the whole task
    would mean re-reading the trail on every link call to say something the
    caller did not ask about, and would hide the one fact it did: whether this
    call moved a row.
    """
    return {
        "task_id": task_id,
        "journal_id": journal_id,
        "attached": attached,
        "changed": changed,
    }


def _task_to_dict(task: Task, intermediate_journal_ids: list[int]) -> dict[str, Any]:
    """The answer every task-returning tool gives.

    ``intermediate_journal_ids`` is passed in rather than read here, and every
    caller supplies one, so a task looks the same whichever tool produced it —
    ``get_task`` included, which builds on this dict rather than beside it.
    Before that tool existed a trail left out of a write's answer was
    *unreachable* rather than merely inconvenient; it is now readable directly,
    and the field stays on every answer so an agent needs one shape, not two.
    """
    return {
        "id": task.id,
        "text": task.text,
        "status": str(task.status),
        "creating_journal_id": task.creating_journal_id,
        "due_journal_id": task.due_journal_id,
        "intermediate_journal_ids": intermediate_journal_ids,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


@mcp_unified_error_handler("create_task", "task")
async def create_task(
    creating_journal_id: Annotated[
        int,
        Field(
            ge=1,
            le=INT32_MAX,
            description=(
                "The journal the commitment arose in — the entry you were "
                "reading or writing when it came up. Never changes."
            ),
        ),
    ],
    due_journal_id: Annotated[
        int,
        Field(
            ge=1,
            le=INT32_MAX,
            description=(
                "The journal the task is due in. Must be an existing journal of "
                "yours dated in the future: today is not the future, and a "
                "multi-day journal already under way is dated by the day it "
                "started. Create the journal first if the day you want has none."
            ),
        ),
    ],
    text: Annotated[
        str, Field(description="The commitment, as plain text. Required and non-empty.")
    ],
    contact_ids: Annotated[
        list[Annotated[int, Field(ge=1, le=INT32_MAX)]] | None,
        Field(
            description=(
                "Optional ids of contacts this task involves. Duplicates are "
                "ignored; every id must be an existing contact."
            )
        ),
    ] = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_service: TaskService = mcp_depends(get_task_service),
) -> str:
    """
    Create a task: something to do, anchored to the journal it is due in.

    Tasks are always attached to journals — there is no separate task list and
    no due *date*. To make a task due on a particular day, that day's journal
    must already exist; name it as due_journal_id. The creating and due journal
    may be the same one.

    Rejections are actionable rather than generic: a journal that does not exist
    or is not yours is reported as not found naming which anchor it was, and a
    due journal that is not future-dated comes back with both its date and
    today's so a later journal can be chosen.

    Returns:
        JSON string with the created task: id, text, status (always "not_done"
        on creation), both journal anchors, the journals it has passed through
        (always empty on creation), and timestamps.
    """
    user_id = await get_current_user_id()

    # A task an assistant created has to read as one an assistant created. The
    # service defaults to ``SYSTEM``, so saying nothing here would make an
    # agent's work indistinguishable from an internal one in the user's own
    # history — the distinction the activity-history specification asks for by
    # name.
    created, trail = await task_service.create_task_with_trail(
        user_id=user_id,
        creating_journal_id=creating_journal_id,
        due_journal_id=due_journal_id,
        text=text,
        transaction=db_connection,
        contact_ids=contact_ids,
        source=Provenance.MCP,
        changed_by="mcp",
    )
    return json.dumps(_task_to_dict(created, trail), indent=2)


@mcp_unified_error_handler("set_task_status", "task")
async def set_task_status(
    task_id: Annotated[
        int, Field(ge=1, le=INT32_MAX, description="The id of the task to change.")
    ],
    status: Annotated[
        TaskStatus,
        Field(
            description=(
                "The status to move the task to. 'not_done' is outstanding, "
                "'done' is met, 'cancelled' is no longer relevant."
            )
        ),
    ],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_service: TaskService = mcp_depends(get_task_service),
) -> str:
    """
    Mark a task done, not done, or cancelled.

    No journal is involved: marking a task done or cancelled needs no journal
    and creates no journal link, so a task whose due journal has already passed
    can still be completed or cancelled where it stands.

    Done is reversible — a task marked done can be moved back to not done.
    Cancelled is not left this way: a cancelled task is reopened by
    **retargeting** it onto a new future journal, which returns it to not done,
    so asking here for not_done or done on a cancelled task is refused and the
    message says what to do instead. Setting the status a task already has
    changes nothing.

    Returns:
        JSON string with the task: id, text, status, both journal anchors, the
        journals it has passed through, and timestamps.
    """
    user_id = await get_current_user_id()

    updated, trail = await task_service.set_status_with_trail(
        user_id=user_id,
        task_id=task_id,
        status=status,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )
    return json.dumps(_task_to_dict(updated, trail), indent=2)


@mcp_unified_error_handler("link_task_to_contact", "task")
async def link_task_to_contact(
    task_id: Annotated[
        int, Field(ge=1, le=INT32_MAX, description="The id of the task to link.")
    ],
    contact_id: Annotated[
        int,
        Field(
            ge=1,
            le=INT32_MAX,
            description=(
                "The id of the contact the task involves. Must be an existing contact."
            ),
        ),
    ],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_service: TaskService = mcp_depends(get_task_service),
) -> str:
    """
    Reference a contact from a task.

    The link is a **plain reference** and nothing more: unlike a journal-contact
    link, it records no relationship type, no role and no attendance status, so
    there is nothing to send but the two ids. Contacts are never inferred from
    the task text — a person is on a task only because somebody linked them.

    Contact links can be changed in any status, including on a task that is
    already done or cancelled. Linking a contact that is already linked is
    accepted and changes nothing, so a retry is safe.

    Returns:
        JSON string with task_id, contact_id, linked (the resulting state, and
        true here) and changed (whether this call created the link, false when
        it was already there).
    """
    user_id = await get_current_user_id()

    changed = await task_service.link_contact(
        user_id=user_id,
        task_id=task_id,
        contact_id=contact_id,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )
    return json.dumps(
        _link_to_dict(task_id, contact_id, linked=True, changed=changed), indent=2
    )


@mcp_unified_error_handler("unlink_task_from_contact", "task")
async def unlink_task_from_contact(
    task_id: Annotated[
        int, Field(ge=1, le=INT32_MAX, description="The id of the task to unlink.")
    ],
    contact_id: Annotated[
        int,
        Field(
            ge=1,
            le=INT32_MAX,
            description="The id of the contact to stop referencing.",
        ),
    ],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_service: TaskService = mcp_depends(get_task_service),
) -> str:
    """
    Stop referencing a contact from a task.

    Removes the link only — the contact and the task are both left alone, and no
    journal is involved. Works in any status, and unlinking a contact that is
    not linked is accepted rather than refused, so a retry is safe. Deleting the
    contact itself removes its task links automatically, so this is not needed
    for that.

    Returns:
        JSON string with task_id, contact_id, linked (the resulting state, and
        false here) and changed (whether this call removed a link, false when
        there was none).
    """
    user_id = await get_current_user_id()

    changed = await task_service.unlink_contact(
        user_id=user_id,
        task_id=task_id,
        contact_id=contact_id,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )
    return json.dumps(
        _link_to_dict(task_id, contact_id, linked=False, changed=changed), indent=2
    )


@mcp_unified_error_handler("retarget_task", "task")
async def retarget_task(
    task_id: Annotated[
        int, Field(ge=1, le=INT32_MAX, description="The id of the task to retarget.")
    ],
    due_journal_id: Annotated[
        int,
        Field(
            ge=1,
            le=INT32_MAX,
            description=(
                "The journal the task should now be due in. Must be an existing "
                "journal of yours dated in the future: today is not the future, "
                "and a multi-day journal already under way is dated by the day "
                "it started. The rule is re-checked here whatever the task's "
                "current status, so create the journal first if the day you "
                "want has none."
            ),
        ),
    ],
    acknowledge_reopen: Annotated[
        StrictBool,
        Field(
            description=(
                "Confirms that reopening a task which is already done is "
                "intended. Without it, retargeting a done task is refused. "
                "Ignored for a task that is not done or is cancelled, neither "
                "of which needs confirming. Must be a JSON boolean — 1, "
                '"true" and "yes" are refused rather than treated as a '
                "confirmation."
            )
        ),
    ] = False,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_service: TaskService = mcp_depends(get_task_service),
) -> str:
    """
    Move a task to a different due journal, keeping the one it is leaving.

    This is how a deadline is extended, and it is the only way a cancelled task
    is reopened — it is what set_task_status tells you to do when it refuses to
    leave cancelled. The previous due journal is kept automatically as an
    intermediate journal, so the trail of a repeatedly-deferred task stays
    visible on the journals it passed through.

    Retargeting always leaves the task **not done**. For a task that is already
    done that means reopening it, which is rarely what moving a date was meant
    to do, so it is refused unless acknowledge_reopen is true; the refusal says
    so. A cancelled task needs no such confirmation.

    Asking for the journal the task is already due in changes nothing at all.
    The journal the task is *leaving* is never checked, so a task whose due
    journal has already passed can be moved onto a future one.

    Returns:
        JSON string with the task: id, text, status (always "not_done" after a
        real retarget), both journal anchors, the journals it has passed
        through — including the one it just left — and timestamps.
    """
    user_id = await get_current_user_id()

    retargeted, trail = await task_service.retarget_due_journal_with_trail(
        user_id=user_id,
        task_id=task_id,
        due_journal_id=due_journal_id,
        transaction=db_connection,
        acknowledge_reopen=acknowledge_reopen,
        source=Provenance.MCP,
        changed_by="mcp",
    )
    return json.dumps(_task_to_dict(retargeted, trail), indent=2)


@mcp_unified_error_handler("update_task_text", "task")
async def update_task_text(
    task_id: Annotated[
        int, Field(ge=1, le=INT32_MAX, description="The id of the task to reword.")
    ],
    text: Annotated[
        str,
        Field(
            description=(
                "The task's new text. Replaces the existing text entirely — "
                "send the whole commitment, not an addition to it. Required "
                "and non-empty."
            )
        ),
    ],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_service: TaskService = mcp_depends(get_task_service),
) -> str:
    """
    Reword a task, in any status.

    Text is editable at any time and in any status, including on a task that is
    done or cancelled and on one whose due journal has already passed — nothing
    about a task's state makes its wording unfixable.

    No journal is involved and none is linked: rewording a task does not attach
    it to whatever journal the conversation happens to be about. Use the journal
    link tools for that.

    Returns:
        JSON string with the task: id, text, status, both journal anchors, the
        journals it has passed through, and timestamps.
    """
    user_id = await get_current_user_id()

    updated, trail = await task_service.update_task_with_trail(
        user_id=user_id,
        task_id=task_id,
        text=text,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )
    return json.dumps(_task_to_dict(updated, trail), indent=2)


@mcp_unified_error_handler("delete_task", "task")
async def delete_task(
    task_id: Annotated[
        int,
        Field(
            ge=1,
            le=INT32_MAX,
            description="The id of the task to delete permanently.",
        ),
    ],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_service: TaskService = mcp_depends(get_task_service),
) -> str:
    """
    Delete a task permanently. Prefer cancelling it instead.

    Cancelling is the ordinary way to retire a task: call set_task_status with
    'cancelled'. A cancelled task stays part of the record of what the user
    committed to, and can be reopened later by retargeting it onto a new future
    journal. Deleting is the exception, for genuine mistakes — a duplicate, or
    something recorded against the wrong thing — and it cannot be undone.

    The task's journal and contact links go with it. The journals and contacts
    themselves are untouched, including the journals it was created in and due
    in.

    Deleting a task that does not exist, or is not yours, reports not found —
    including a second delete of a task already deleted.

    Returns:
        JSON string confirming the deletion: deleted (true) and task_id.
    """
    user_id = await get_current_user_id()

    await task_service.delete_task(
        user_id=user_id,
        task_id=task_id,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )
    return json.dumps({"deleted": True, "task_id": task_id}, indent=2)


@mcp_unified_error_handler("attach_intermediate_journal_to_task", "task")
async def attach_intermediate_journal_to_task(
    task_id: Annotated[
        int, Field(ge=1, le=INT32_MAX, description="The id of the task to link.")
    ],
    journal_id: Annotated[
        int,
        Field(
            ge=1,
            le=INT32_MAX,
            description=(
                "The id of the journal the task was discussed or revisited in. "
                "Must be an existing journal of yours, and must not already be "
                "the task's creating or due journal."
            ),
        ),
    ],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_service: TaskService = mcp_depends(get_task_service),
) -> str:
    """
    Note that a task came up in another journal, as an intermediate link.

    An intermediate journal is one the task was **discussed, revisited, or
    previously due** in, so the task stays visible there as well as on the two
    journals it is anchored to. The link carries no role and no relationship
    type: it records that the task and the journal are connected, and nothing
    more.

    **The two anchors are not reachable from here.** A task's creating journal
    and its due journal are properties of the task itself, not links: the
    creating one is fixed when the task is created and never changes, and the
    due one is moved by retargeting. Naming either of them here is refused, and
    the message says which it was.

    Attaching a journal that is already attached is accepted and changes
    nothing, so a retry is safe. Retargeting a task keeps its previous due
    journal as an intermediate link automatically — this tool is for the links a
    person asks for, and nothing infers one from an ordinary edit.

    Returns:
        JSON string with task_id, journal_id, attached (the resulting state, and
        true here) and changed (whether this call created the link, false when
        it was already there).
    """
    user_id = await get_current_user_id()

    changed = await task_service.attach_intermediate_journal(
        user_id=user_id,
        task_id=task_id,
        journal_id=journal_id,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )
    return json.dumps(
        _journal_link_to_dict(task_id, journal_id, attached=True, changed=changed),
        indent=2,
    )


@mcp_unified_error_handler("detach_intermediate_journal_from_task", "task")
async def detach_intermediate_journal_from_task(
    task_id: Annotated[
        int, Field(ge=1, le=INT32_MAX, description="The id of the task to unlink.")
    ],
    journal_id: Annotated[
        int,
        Field(
            ge=1,
            le=INT32_MAX,
            description="The id of the intermediate journal to stop referencing.",
        ),
    ],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_service: TaskService = mcp_depends(get_task_service),
) -> str:
    """
    Remove an intermediate-journal link from a task.

    Removes the link only — the task and the journal are both left alone. Works
    in any status, and detaching a journal that is not attached is accepted
    rather than refused, so a retry is safe. Deleting the journal itself removes
    its intermediate links automatically, so this is not needed for that.

    **One shape is not retry-safe**, and it is worth knowing before you build a
    retry on this: a journal that is *both* an anchor and an intermediate journal
    succeeds the first time and is refused the second, because once the link row
    is gone this call is indistinguishable from asking to unlink the task's due
    journal. Everywhere else, repeating the call is harmless.

    **The task's creating and due journals cannot be removed this way** and
    naming either is refused rather than quietly doing nothing: those roles are
    not links at all. To move a task off the journal it is due in, **retarget**
    it onto a new future journal; the creating journal never changes. A journal
    that is *both* an anchor and an intermediate journal — which happens when a
    task is retargeted onto a journal it already mentioned — keeps its
    intermediate link removable; only the anchor role is out of reach.

    Returns:
        JSON string with task_id, journal_id, attached (the resulting state, and
        false here) and changed (whether this call removed a link, false when
        there was none).
    """
    user_id = await get_current_user_id()

    changed = await task_service.detach_intermediate_journal(
        user_id=user_id,
        task_id=task_id,
        journal_id=journal_id,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )
    return json.dumps(
        _journal_link_to_dict(task_id, journal_id, attached=False, changed=changed),
        indent=2,
    )


def _journal_ref_to_dict(ref: TaskJournalRef) -> dict[str, Any]:
    """One of a task's journals, as a read tool hands it over.

    The date is a **date**, already resolved in the user's timezone — the same
    one the lapse rule judged the task against. Sending an instant would invite
    an agent to re-derive the day in UTC and disagree with the verdict beside it.
    """
    return {
        "id": ref.id,
        "title": ref.title,
        "date": ref.date.isoformat(),
        "cancelled": ref.cancelled,
    }


def _read_model_to_dict(model: TaskReadModel) -> dict[str, Any]:
    """A task as the read tools return it.

    A **superset** of what the write tools return: every field ``_task_to_dict``
    carries is here, including ``intermediate_journal_ids``, with the resolved
    journals, the contacts and the lapse added. An agent that learned the shape
    from ``create_task`` does not have to learn a second one to read the task
    back.
    """
    return {
        **_task_to_dict(model.task, [ref.id for ref in model.intermediate_journals]),
        "creating_journal": _journal_ref_to_dict(model.creating_journal),
        "due_journal": _journal_ref_to_dict(model.due_journal),
        "intermediate_journals": [
            _journal_ref_to_dict(ref) for ref in model.intermediate_journals
        ],
        "contacts": [
            {
                "id": contact.id,
                "display_name": contact.display_name,
                "photo_url": contact.photo_url,
            }
            for contact in model.contacts
        ],
        # Taken from the model rather than recomputed from the reason, so the
        # flag and the reason can never disagree about the same task.
        "lapsed": model.lapsed,
        "lapse_reason": (
            str(model.lapse_reason) if model.lapse_reason is not None else None
        ),
    }


def _groups_to_dict(groups: JournalTaskGroups) -> dict[str, Any]:
    """A journal's tasks, nested under the role each link holds.

    **The roles are the structure here**, unlike the JSON:API endpoint, which
    lists each task once with its roles as an attribute because the
    specification forbids a duplicate resource in ``data``. JSON has no such
    rule, and an agent asked to list tasks "by link role" wants to read the
    roles off the answer rather than reassemble them — so a task holding two of
    the journal's roles appears under both, carrying ``link_roles`` so a nested
    copy still says which groups it is in. Under a ``role`` filter those roles
    narrow with the groups, so a copy never names a group this answer left
    empty.
    """
    return {
        "journal_id": groups.journal_id,
        "groups": {
            str(role): [
                {
                    **_read_model_to_dict(model),
                    "link_roles": [
                        str(held) for held in groups.roles_for(model.task.id or 0)
                    ],
                }
                for model in groups.for_role(role)
            ]
            for role in TaskLinkRole
        },
    }


@mcp_unified_error_handler("get_task", "task")
async def get_task(
    task_id: Annotated[
        int,
        Field(ge=1, le=INT32_MAX, description="The id of the task to read."),
    ],
    task_read_service: TaskReadService = mcp_depends(get_task_read_service),
) -> str:
    """
    Read one task whole: its journals by role, its contacts, and its lapse.

    Use this to check a task's current state before acting on it, or to see what
    a task you created earlier looks like now. Every journal comes back with its
    title and its date rather than as a bare id, so no follow-up lookup is needed
    to describe the task to the user.

    A task is **lapsed** when it is still not done and its due journal has either
    passed or been **cancelled**. Nothing lapses a done or cancelled task. The
    reason says which of the two happened, because they call for different
    follow-ups: a date that went by usually wants the task **retargeted** onto a
    new future journal, which is also how a lapsed or cancelled task is
    resurrected, while a cancelled meeting may mean the commitment no longer
    applies at all. Lapsed is worked out on every read from today's date in the
    user's own timezone — there is no stored flag, and it is not something to
    compute yourself.

    A lapsed task is not broken: it can still be completed, reworded, cancelled
    or retargeted.

    Returns:
        JSON string with the task's id, text, status and timestamps; its
        journals by role — the **creating** journal it arose in, the **due**
        journal it is due in, and the intermediate journals it has passed
        through, given both as ids and as objects carrying title, date and
        whether the journal is a cancelled event; its linked contacts; and
        whether it has lapsed, with the reason.
    """
    user_id = await get_current_user_id()

    model = await task_read_service.read_model(user_id, task_id)
    return json.dumps(_read_model_to_dict(model), indent=2)


@mcp_unified_error_handler("list_journal_tasks", "task")
async def list_journal_tasks(
    journal_id: Annotated[
        int,
        Field(
            ge=1,
            le=INT32_MAX,
            description="The journal whose tasks to list.",
        ),
    ],
    role: Annotated[
        TaskLinkRole | None,
        Field(
            description=(
                "Return only tasks holding this role in the journal. Omit for "
                "all three groups, which is usually what you want."
            )
        ),
    ] = None,
    task_read_service: TaskReadService = mcp_depends(get_task_read_service),
) -> str:
    """
    List the tasks linked to a journal, grouped by how each one is linked.

    A journal has three groups of tasks: those **due** in it, those **created**
    in it, and those merely **mentioned** in it through an intermediate link.
    They are genuinely different things — a task due here is a commitment
    landing on this day, one created here arose here and is due elsewhere, and a
    mention is a journal the task passed through.

    A task can appear in **more than one group**: the same journal may be both
    its anchors, and retargeting a task onto a journal it already mentioned
    leaves that mention in place. Each copy carries link_roles, so do not count
    rows across groups as distinct tasks.

    **Every linked task is listed, in every status** — done, cancelled and
    lapsed included. A journal is where a lapsed task is meant to be found
    again, so it is marked rather than hidden, and a done task's link to the
    journal it arose in is part of the record. There is deliberately no status
    filter: the product has no "everything still outstanding" list, and tasks
    are worked with on journals and on the home dashboard, nowhere else.

    Tasks are ordered by their due journal's date, soonest first.

    Returns:
        JSON string with journal_id and a groups object keyed due, created and
        mentioned, each holding the same task shape get_task returns plus
        link_roles. A journal of yours with no tasks returns three empty groups;
        a journal that does not exist or is not yours is an error.
    """
    user_id = await get_current_user_id()

    groups = await task_read_service.read_models_for_journal(
        user_id, journal_id, role=role
    )
    return json.dumps(_groups_to_dict(groups), indent=2)


def register_task_tools(mcp: FastMCP[None]) -> None:
    """Register task MCP tools with the FastMCP server."""
    mcp.add_tool(create_task)
    mcp.add_tool(set_task_status)
    mcp.add_tool(retarget_task)
    mcp.add_tool(update_task_text)
    mcp.add_tool(delete_task)
    mcp.add_tool(link_task_to_contact)
    mcp.add_tool(unlink_task_from_contact)
    mcp.add_tool(attach_intermediate_journal_to_task)
    mcp.add_tool(detach_intermediate_journal_from_task)
    mcp.add_tool(get_task)
    mcp.add_tool(list_journal_tasks)
