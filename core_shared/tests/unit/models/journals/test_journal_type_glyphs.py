"""Unit tests for the journal-type glyph mapping.

The glyphs give the logbook PDF the same visual type cues the UI gets from
``JournalTypeBadges.tsx``, without embedding image assets. Two properties matter
and are pinned here: the mapping is exhaustive (a new journal type cannot ship
without a glyph), and every outdoor subtype gets a *distinct* glyph — the UI
deliberately reuses icons across pairs (Mountain, Waves, Snowflake,
ArrowDownToLine, Wrench), which the PDF must not do.
"""

import pytest

from core_shared.models.journals import (
    JOURNAL_TYPE_GLYPHS,
    JournalType,
    OutdoorActivitySubtype,
    glyph_for_journal_type,
)


def test_every_journal_type_has_a_glyph() -> None:
    """Every JournalType member is mapped, so no type renders unlabelled."""
    missing = [
        journal_type
        for journal_type in JournalType
        if journal_type not in JOURNAL_TYPE_GLYPHS
    ]
    assert missing == []


def test_glyphs_are_single_characters() -> None:
    """Each glyph is one character, so it sits inline beside a type label."""
    for journal_type, glyph in JOURNAL_TYPE_GLYPHS.items():
        assert len(glyph) == 1, f"{journal_type} glyph is not a single character"


def test_outdoor_subtype_glyphs_are_distinct() -> None:
    """No two outdoor subtypes share a glyph.

    The spec requires one distinct glyph per outdoor subtype even where the UI
    reuses a lucide icon (e.g. Mountain for both caving and outdoor activity).
    """
    outdoor_types = [JournalType(subtype.value) for subtype in OutdoorActivitySubtype]
    # The two outdoor types that sit outside the subtype enum but are still
    # rendered as outdoor activities in the logbook.
    outdoor_types += [JournalType.OUTDOOR_ACTIVITY, JournalType.OUTDOOR_PLANNING]

    glyphs = [JOURNAL_TYPE_GLYPHS[journal_type] for journal_type in outdoor_types]

    assert len(glyphs) == len(set(glyphs)), "outdoor subtypes share a glyph"


@pytest.mark.parametrize("raw", ["CANYONING", "canyoning", "Canyoning"])
def test_lookup_accepts_the_pipeline_type_form(raw: str) -> None:
    """Lookup tolerates the uppercase type strings the logbook pipeline uses."""
    assert glyph_for_journal_type(raw) == JOURNAL_TYPE_GLYPHS[JournalType.CANYONING]


@pytest.mark.parametrize("raw", ["", "NOT_A_TYPE", "  "])
def test_lookup_returns_none_for_unknown_type(raw: str) -> None:
    """Unknown types degrade to no glyph rather than failing an export."""
    assert glyph_for_journal_type(raw) is None
