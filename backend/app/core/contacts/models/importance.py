"""How important a contact is, and the order that judgement is made in.

The system has always had an opinion about which contacts matter most — a
favourite outranks everything, then whoever has been in recent journals, then
whoever has been edited recently — but until now that opinion lived only inside
the search indexer, half of it as a Python loop and half of it as a list of
MeiliSearch ranking-rule strings. The home dashboard needs the same judgement to
order upcoming important dates, and it must reach it without MeiliSearch being
up, so the judgement moves here and both consumers read it from one place.

**The order is stated once.** ``CONTACT_IMPORTANCE_ORDER`` is the statement, and
the index's custom ranking rules are derived from it rather than repeating it;
``ranking_key`` walks the same tuple. Adding a fourth signal is one edit to the
tuple and one field on the model, not three edits in three files that have to be
kept agreeing by a test.

**It is a precedence, not a score.** Signals are compared in order and the first
one to differ decides; a contact with fifty recent journals never overtakes a
favourite. Weighting them into a single number would be a different and much
harder claim about how one journal trades against one edit, and neither the
search ranking nor the dashboard needs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from datetime import datetime

# Most significant first. The search index derives its custom ranking rules from
# this tuple (see ``CONTACTS_INDEX_SETTINGS``) and ``ranking_key`` walks it, so
# this is the only place the precedence is written down.
CONTACT_IMPORTANCE_ORDER: Final[tuple[str, ...]] = (
    "is_favourite",
    "journal_count_30d",
    "activity_count_30d",
)

# The window "recent" means, for both counts. Thirty days is what the search
# ranking has always used; it is named here so the two counts cannot drift apart
# and so a caller can see what it is being told without reading SQL.
IMPORTANCE_WINDOW_DAYS: Final[int] = 30


@dataclass(frozen=True, slots=True)
class ContactImportance:
    """One contact's importance signals, as at the moment they were read.

    Frozen because it is a projection of rows, not a thing to adjust: a caller
    that wants a different answer has to ask the database again.

    Attributes:
        contact_id: The contact these signals describe.
        is_favourite: Whether the user has marked the contact a favourite.
        journal_count_30d: Journals mentioning the contact in the window.
        activity_count_30d: Recorded field changes to the contact or one of its
            methods, addresses, notes or tags in the window.
        last_activity_at: The most recent of the contact's own ``updated_at``,
            its newest journal and its newest recorded change — the freshest
            moment anything about the contact moved. Never ``None`` for a
            contact that exists, because its ``updated_at`` always does, but
            typed optional so a caller cannot assume otherwise from a partial
            projection.
    """

    contact_id: int
    is_favourite: bool
    journal_count_30d: int
    activity_count_30d: int
    last_activity_at: datetime | None

    @property
    def ranking_key(self) -> tuple[int, ...]:
        """A sort key placing the most important contact first, ascending.

        The values are negated so this composes into a single ascending sort
        alongside keys that are naturally ascending — the dashboard orders
        upcoming dates by ``(occurrence_date, *importance.ranking_key)``, soonest
        date first and, within a date, most important contact first, in one pass
        and without a ``reverse`` that would flip the date too.

        Returns:
            One integer per signal in ``CONTACT_IMPORTANCE_ORDER``, in that
            order. ``bool`` is an ``int`` in Python, so a favourite contributes
            ``-1`` and a non-favourite ``0``.
        """
        return tuple(-int(getattr(self, signal)) for signal in CONTACT_IMPORTANCE_ORDER)
