from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.journal.models.repositories import JournalContactRelationshipRepository


@dataclass
class TransitionResult:
    """Result of a bulk status transition operation."""

    transitioned_count: int
    batches_processed: int


async def transition_attending_to_attended(
    repo: JournalContactRelationshipRepository,
    now: datetime | None = None,
    batch_size: int = 500,
    max_iterations: int = 100,
) -> TransitionResult:
    """
    Transition ATTENDING statuses to ATTENDED for past events.

    Processes the transitions in batches to avoid locking the entire table
    and consuming too much memory/transaction log. The internal loop prevents
    infinite loops with max_iterations.

    Args:
        repo: The repository to run the transitions on
        now: Current time (defaults to utcnow)
        batch_size: Number of records to transition per batch
        max_iterations: Safety limit to prevent infinite loops (max total records = batch_size * max_iterations)

    Returns:
        TransitionResult summarizing the operation
    """
    if now is None:
        now = datetime.now(UTC)

    total_transitioned = 0
    batches_processed = 0

    while batches_processed < max_iterations:
        updated_count = await repo.transition_attending_to_attended(
            before=now, batch_size=batch_size
        )

        total_transitioned += updated_count
        batches_processed += 1

        # If we updated fewer rows than the batch size, we're done
        if updated_count < batch_size:
            break

    return TransitionResult(
        transitioned_count=total_transitioned, batches_processed=batches_processed
    )
