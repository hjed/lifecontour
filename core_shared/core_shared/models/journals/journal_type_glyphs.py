"""Icon glyphs for journal types.

Gives the logbook PDF the same visual type cues the UI gets from
``JournalTypeBadges.tsx``, using unicode glyphs rather than image assets. The
glyphs mirror the semantics of the UI's lucide icons as closely as a text glyph
allows, with one exception: the UI reuses an icon across several pairs (Mountain
for outdoor activity and caving, Waves for kayaking and snorkelling, Snowflake
for both ski types, ArrowDownToLine for abseiling and diving, Wrench for both
gear types), whereas every **outdoor subtype** here gets a distinct glyph so two
different activities never read the same on the page.

Every glyph is drawn from a range a standard DejaVu-class text font covers — the
PDF renderer registers such a font for these runs, and pins the coverage with a
test, because the built-in PDF fonts render an uncovered codepoint as an empty
box.
"""

from __future__ import annotations

from .journal_types import JournalType

# One glyph per journal type. The UI icon each mirrors is named alongside.
JOURNAL_TYPE_GLYPHS: dict[JournalType, str] = {
    # Base types
    JournalType.NOTE: "✎",  # FileText
    JournalType.EVENT: "▤",  # Calendar
    JournalType.MOOD_RATING: "♥",  # Heart
    JournalType.PLAN: "☑",  # ClipboardList
    JournalType.TRAVEL: "✈",  # Plane
    JournalType.PHOTO_ALBUM: "❏",  # Image
    JournalType.FITNESS: "⚡",  # Activity
    JournalType.JOGGING: "➤",  # Timer
    # Outdoor activity types — each distinct
    JournalType.OUTDOOR_ACTIVITY: "▲",  # Mountain
    JournalType.BUSHWALKING: "☘",  # Trees
    JournalType.ABSEILING_TRIP: "⇩",  # ArrowDownToLine
    JournalType.CANYONING: "≋",  # Droplets
    JournalType.CAVING: "◭",  # Mountain (distinct from outdoor activity)
    JournalType.CANOEING: "⚓",  # Ship
    JournalType.CLIMBING: "⇧",  # TrendingUp
    JournalType.KAYAKING: "≈",  # Waves
    JournalType.CROSS_COUNTRY_SKIING: "❄",  # Snowflake
    JournalType.SNORKELLING: "∿",  # Waves (distinct from kayaking)
    JournalType.DIVING: "⇓",  # ArrowDownToLine (distinct from abseiling)
    JournalType.DOWNHILL_SKIING: "❅",  # Snowflake (distinct from XC skiing)
    # Supporting types
    JournalType.OUTDOOR_PLANNING: "⚑",  # MapPin
    JournalType.OUTDOOR_TRAINING: "◎",  # Target
    JournalType.GEAR_MAINTENANCE: "⚒",  # Wrench
    JournalType.GEAR_USAGE: "⚙",  # Wrench (distinct from maintenance)
}


def glyph_for_journal_type(journal_type: str) -> str | None:
    """Return the glyph for a journal type name, or ``None`` if unknown.

    Accepts the uppercase type names the logbook export pipeline carries (the
    repository's SQL labels them ``'CANYONING'``) as well as the enum's own
    lowercase values. An unrecognised name yields ``None`` so a type this
    mapping has not caught up with degrades to a plain label instead of failing
    an export.
    """
    try:
        resolved = JournalType(journal_type.strip().lower())
    except ValueError:
        return None
    return JOURNAL_TYPE_GLYPHS.get(resolved)
