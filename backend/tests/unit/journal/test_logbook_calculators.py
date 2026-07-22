"""Unit tests for the logbook index calculators.

Covers the pure reducers behind the PDF's linked indexes: the journals each
participant appears in, and the activity-type index that lists every journal
under each of its types.
"""

import datetime

import pytest
from core_shared.models.journals import (
    ActivityTypeIndexCalculator,
    LogbookEntryContact,
    LogbookEntryData,
    ParticipantIndexCalculator,
)

# ─── Fixture helpers ─────────────────────────────────────────────────


def _make_entry(
    entry_id: int,
    title: str = "Test Entry",
    types: list[str] | None = None,
    day: int = 15,
) -> LogbookEntryData:
    """Create a minimal LogbookEntryData for testing."""
    moment = datetime.datetime(2024, 1, day, tzinfo=datetime.UTC)
    from core_shared.models.journals import EventDateRange

    return LogbookEntryData(
        id=entry_id,
        title=title,
        content="",
        event_date_range=EventDateRange(start=moment, end=moment),
        parent_id=None,
        journal_types=types if types is not None else ["BUSHWALKING"],
    )


def _with_contact(
    entry: LogbookEntryData,
    contact_id: int = 1,
    name: str = "Alice Smith",
    role: str = "PARTICIPANT",
) -> LogbookEntryData:
    """Attach a contact to an entry and return it."""
    entry.contacts.append(
        LogbookEntryContact(contact_id=contact_id, name=name, role=role)
    )
    return entry


# ─── Participant index ───────────────────────────────────────────────


@pytest.mark.unit
class TestParticipantIndexJournals:
    """The participant index lists the journals each contact appears in."""

    def test_participant_journals_match_appearance_count(self) -> None:
        """Each counted appearance contributes one linkable journal reference."""
        entries = [
            _with_contact(_make_entry(1, title="Ridge Walk", day=1)),
            _with_contact(_make_entry(2, title="Claustral Canyon", day=2)),
            _with_contact(_make_entry(3, title="Jenolan Caves", day=3)),
        ]

        result = ParticipantIndexCalculator().calculate(entries)

        assert len(result) == 1
        alice = result[0]
        assert alice.appearances == len(alice.journals) == 3
        assert [journal.journal_id for journal in alice.journals] == [1, 2, 3]
        assert [journal.title for journal in alice.journals] == [
            "Ridge Walk",
            "Claustral Canyon",
            "Jenolan Caves",
        ]

    def test_participant_journals_name_the_root_entry(self) -> None:
        """A contact on a child entry is listed against the root, counted once.

        Appearances are counted per root entry so a contact on both the parent
        and its children is not double-counted; the linked journal must be the
        root the reader can navigate to.
        """
        root = _make_entry(1, title="Kanangra Weekend", day=1)
        child = _with_contact(_make_entry(2, title="Saturday Abseil", day=1))
        grandchild = _with_contact(_make_entry(3, title="Afternoon Pitch", day=1))
        child.children = [grandchild]
        root.children = [child]

        other_entries = [
            _with_contact(_make_entry(4, title="Ridge Walk", day=2)),
            _with_contact(_make_entry(5, title="River Paddle", day=3)),
        ]

        result = ParticipantIndexCalculator().calculate([root, *other_entries])

        assert len(result) == 1
        alice = result[0]
        assert alice.appearances == 3
        assert [journal.title for journal in alice.journals] == [
            "Kanangra Weekend",
            "Ridge Walk",
            "River Paddle",
        ]

    def test_participant_index_threshold_boundary(self) -> None:
        """Exactly three appearances qualify; two do not."""
        entries = [
            _with_contact(_make_entry(1, title="One", day=1), contact_id=1),
            _with_contact(_make_entry(2, title="Two", day=2), contact_id=1),
            _with_contact(_make_entry(3, title="Three", day=3), contact_id=1),
        ]
        _with_contact(entries[0], contact_id=2, name="Bob Jones")
        _with_contact(entries[1], contact_id=2, name="Bob Jones")

        result = ParticipantIndexCalculator().calculate(entries)

        assert [participant.name for participant in result] == ["Alice Smith"]
        assert len(result[0].journals) == 3


# ─── Activity-type index ─────────────────────────────────────────────


@pytest.mark.unit
class TestActivityTypeIndexCalculator:
    """The activity-type index lists each type's journals as linkable names."""

    def test_lists_journal_under_every_type(self) -> None:
        """A journal is indexed under every type row it carries.

        Subtype rows are stored verbatim — a canyoning journal also carries the
        bushwalking, abseiling and outdoor-activity rows its type depends on —
        and the index reflects them all (product decision, 2026-07-22).
        """
        entry = _make_entry(
            1,
            title="Claustral Canyon",
            types=["CANYONING", "BUSHWALKING", "ABSEILING_TRIP", "OUTDOOR_ACTIVITY"],
        )

        result = ActivityTypeIndexCalculator().calculate([entry])

        assert [section.activity_type for section in result] == [
            "ABSEILING_TRIP",
            "BUSHWALKING",
            "CANYONING",
            "OUTDOOR_ACTIVITY",
        ]
        for section in result:
            assert [journal.journal_id for journal in section.journals] == [1]
            assert [journal.title for journal in section.journals] == [
                "Claustral Canyon"
            ]

    def test_includes_child_entries(self) -> None:
        """Child activities are indexed alongside the roots, in document order."""
        root = _make_entry(1, title="Blue Mountains Weekend", types=["NOTE"])
        child = _make_entry(2, title="Saturday Bushwalk", types=["BUSHWALKING"])
        grandchild = _make_entry(3, title="Sunday Canyon", types=["CANYONING"])
        child.children = [grandchild]
        root.children = [child]

        result = ActivityTypeIndexCalculator().calculate([root])
        sections = {section.activity_type: section for section in result}

        assert set(sections) == {"NOTE", "BUSHWALKING", "CANYONING"}
        assert [j.title for j in sections["BUSHWALKING"].journals] == [
            "Saturday Bushwalk"
        ]
        assert [j.title for j in sections["CANYONING"].journals] == ["Sunday Canyon"]

    def test_sections_sorted_and_journals_in_document_order(self) -> None:
        """Sections are type-sorted; journals within a section keep document order."""
        entries = [
            _make_entry(1, title="First Walk", types=["BUSHWALKING"], day=1),
            _make_entry(2, title="Cave Trip", types=["CAVING"], day=2),
            _make_entry(3, title="Second Walk", types=["BUSHWALKING"], day=3),
        ]

        result = ActivityTypeIndexCalculator().calculate(entries)

        assert [section.activity_type for section in result] == [
            "BUSHWALKING",
            "CAVING",
        ]
        assert [journal.title for journal in result[0].journals] == [
            "First Walk",
            "Second Walk",
        ]

    def test_journal_listed_once_per_type(self) -> None:
        """A duplicated type row does not duplicate the journal in its section."""
        entry = _make_entry(1, title="Ridge Walk", types=["BUSHWALKING", "BUSHWALKING"])

        result = ActivityTypeIndexCalculator().calculate([entry])

        assert len(result) == 1
        assert [journal.journal_id for journal in result[0].journals] == [1]

    def test_empty_for_no_entries(self) -> None:
        """No entries produce no index sections."""
        assert ActivityTypeIndexCalculator().calculate([]) == []
