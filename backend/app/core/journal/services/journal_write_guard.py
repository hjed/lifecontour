"""The first step of every write to a journal or a row it renders."""

from collections.abc import Sequence
from datetime import datetime
from functools import partial

from core_shared.models.journals import JournalNotFoundError

from app.core.journal.models.repositories import JournalRepository
from app.shared.preconditions import guard_aggregate_write


async def guard_journal_write(
    journal_repo: JournalRepository,
    journal_id: int,
    expected_etags: Sequence[str] | None,
) -> datetime:
    """Lock a journal for a write, refusing a stale precondition.

    Call it first, inside the write's unit of work: see
    :func:`~app.shared.preconditions.guard_aggregate_write`. The locking read
    is not owner-scoped - every caller proves the journal is the user's before
    the write starts (``_require_owned_journal``, the MCP tools' owner-scoped
    read) - so a refusal never names the version of somebody else's journal.

    Returns:
        The journal's version as locked.

    Raises:
        JournalNotFoundError: If the journal is gone.
        PreconditionFailedError: If ``expected_etags`` names a version the
            journal has already moved on from.
    """
    return await guard_aggregate_write(
        resource_type="journals",
        resource_id=journal_id,
        expected_etags=expected_etags,
        lock_and_get_updated_at=partial(
            journal_repo.lock_and_get_updated_at, journal_id
        ),
        not_found=JournalNotFoundError,
    )
