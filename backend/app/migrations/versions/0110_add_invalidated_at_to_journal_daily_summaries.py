"""add invalidated_at to journal_daily_summaries

Revision ID: 0110
Revises: 0109
Create Date: 2026-09-06 23:30:35.112727

A change stamp, not a staleness flag. ITER18-005 Phase 2 settled that
*staleness* is derived — a summary generated before today in the user's zone is
stale — and deliberately added no column for it. This column answers a different
question, and only one: **was this row invalidated after the request that is
about to write to it read its inputs?**

Without it that race is unanswerable. ``get_or_generate`` reads the row, gathers
the day's journals, tasks and dates, then claims the row for generation by
compare-and-set on ``generated_at``. An invalidation landing in between moves
the status to ``PENDING`` and leaves ``generated_at`` untouched, so the claim
still succeeds and the finishing generation writes ``GENERATED`` over the marker
with a summary assembled *before* the change. The day then looks fresh and
describes something that is no longer true, until the next input change or local
midnight.

``NULL`` on every existing row, which is the correct starting value: a row that
has never been invalidated compares equal to a caller that saw no invalidation
(``IS NOT DISTINCT FROM``), so the guard is inert until the first invalidation
touches the row.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0110"
down_revision: str | None = "0109"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable change stamp."""
    op.execute(
        """
        ALTER TABLE journal_daily_summaries
        ADD COLUMN invalidated_at TIMESTAMP WITH TIME ZONE
        """
    )


def downgrade() -> None:
    """Drop it. Nothing reads the column but the generation guard."""
    op.execute(
        """
        ALTER TABLE journal_daily_summaries
        DROP COLUMN invalidated_at
        """
    )
