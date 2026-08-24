"""Turning a daily-summary row into the dashboard's summary section.

One pure function over one decision: of the five statuses a
``journal_daily_summaries`` row can hold, which produce something the headline
card can draw, and which mean the page has no summary to show today.

The answer is not "a row exists". ``FAILED`` is a row, and so is ``DISABLED``,
which is what a day below the two-journal threshold gets — in both cases the
user has no summary for today, which is the state the wireframe renders as one
quiet line saying so while the rest of the page carries on. Those join *no row
at all*, the state of a user whose AI is unconfigured, in returning ``None``:
the section is then **unavailable**, and the envelope's own rule keeps
``data: null`` beside it.

``PENDING`` folds into *generating* rather than earning a state of its own. It
means the summary was invalidated because a journal on that day changed, and to
a reader waiting for words to appear, queued and in-flight are one condition. The
card declares three states, so a fourth on the wire would hand it a branch it has
nowhere to render.

**But nothing currently moves a journal daily summary out of ``PENDING``.**
``SearchIndexerConsumer`` invalidates it; only ``DailySummaryService`` generates,
and it is reached from the daily-summary endpoints alone — which this service
deliberately does not call, because a page load must not write. So *generating*
overstates what is happening until the user asks for a regeneration or opens the
journals view. It is still the least wrong of the three states — the other two
say "no summary today" over a summary that exists, or show prose the day has
outgrown — and the card's Regenerate control sits outside all three, so the
reader always has the action that resolves it. ITER18-005 makes the state honest
by regenerating today's summary on read. Recorded as a follow-up on ITER18-004
Phase 2 rather than settled here, because when a summary is regenerated is that
iteration's subject and not this one's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core_shared.models.contacts.entities import SummaryStatus

from app.core.dashboard.models.sections import (
    DashboardSummaryState,
    SummarySectionData,
)

if TYPE_CHECKING:
    from core_shared.models.journals.daily_summary import JournalDailySummary

# Only these three describe a summary the page can show, and the value is the
# state it shows it in. A status missing from here has nothing to display, so
# adding a sixth to the enum without deciding its place fails the exhaustiveness
# test rather than defaulting quietly to one behaviour or the other.
_SHOWABLE: dict[SummaryStatus, DashboardSummaryState] = {
    SummaryStatus.GENERATED: DashboardSummaryState.GENERATED,
    SummaryStatus.PENDING: DashboardSummaryState.GENERATING,
    SummaryStatus.GENERATING: DashboardSummaryState.GENERATING,
}


def summary_section_for(
    summary: JournalDailySummary | None,
) -> SummarySectionData | None:
    """The summary section's payload, or ``None`` when there is none to show.

    Args:
        summary: Today's row, or ``None`` if the user has no summary for today.

    Returns:
        The payload the headline card renders, or ``None`` — which the service
        turns into an unavailable section, and the card into its quiet line.
    """
    if summary is None:
        return None

    state = _SHOWABLE.get(summary.status)
    if state is None:
        return None

    return SummarySectionData(
        state=state,
        # The entity's own accessor, so the dashboard withholds prose on exactly
        # the days the journals view does.
        summary_text=summary.get_display_text(),
        journal_count=summary.journal_count,
        event_count=summary.event_count,
        contact_count=summary.contact_count,
        mood_average=summary.mood_average,
    )
