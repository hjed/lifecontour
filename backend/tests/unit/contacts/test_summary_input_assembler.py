"""Unit tests for SummaryInputAssembler — bounded input gathering for AI summaries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.contacts.entities import (
    Contact,
    ContactNote,
    ContactRelationship,
    ContactSummary,
    ImportantDate,
    RelationshipType,
    SummaryDisabledReason,
    SummaryStatus,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)

from app.core.contacts.services.summary_generation_service import (
    ActivityStatsBucket,
    SummaryInput,
    SummaryInputAssembler,
)


def _make_history_entry(
    field_name: str = "first_name",
    old_value: str | None = "Old",
    new_value: str | None = "New",
    created_at: str | None = None,
) -> MagicMock:
    """Helper to create a mock ContactFieldHistoryEntry."""
    entry = MagicMock()
    entry.field_name = field_name
    entry.old_value = old_value
    entry.new_value = new_value
    entry.entity_type = "contact"
    entry.entity_id = 1
    entry.changed_by = "system"
    entry.created_at = created_at or datetime.now(tz=UTC).isoformat()
    return entry


def _make_journal_relationship(journal_id: int, contact_id: int = 1) -> MagicMock:
    """Helper to create a mock JournalContactRelationship."""
    rel = MagicMock()
    rel.journal_id = journal_id
    rel.contact_id = contact_id
    rel.relationship_type = MagicMock(value="participant")
    rel.created_at = datetime.now(tz=UTC)
    return rel


def _make_journal(
    journal_id: int,
    title: str = "Test Journal",
    content: str = "Test content",
    start: datetime | None = None,
) -> MagicMock:
    """Helper to create a mock Journal entity."""
    journal = MagicMock()
    journal.id = journal_id
    journal.title = title
    journal.content = content
    journal.event_date_range = MagicMock()
    journal.event_date_range.start = start or datetime.now(tz=UTC)
    journal.event_date_range.end = (start or datetime.now(tz=UTC)) + timedelta(hours=1)
    return journal


def _make_assembler(
    contact: Contact | None = None,
    notes: list[ContactNote] | None = None,
    history_entries: list[MagicMock] | None = None,
    relationships: list[ContactRelationship] | None = None,
    journal_relationships: list[MagicMock] | None = None,
    journals: list[MagicMock] | None = None,
    summary: ContactSummary | None = None,
    all_journal_relationships: list[MagicMock] | None = None,
    series_repo: AsyncMock | None = None,
) -> SummaryInputAssembler:
    """Create a SummaryInputAssembler with mock repositories."""
    contact_repo = AsyncMock()
    contact_repo.find_by_id = AsyncMock(
        return_value=contact
        or Contact(
            first_name="John",
            last_name="Doe",
            id=1,
            company="Acme",
            job_title="Engineer",
            notes=notes or [],
            relationships=relationships or [],
            important_dates=[],
        )
    )

    history_repo = AsyncMock()
    history_repo.get_contact_history = AsyncMock(return_value=history_entries or [])

    journal_relationship_repo = AsyncMock()
    journal_relationship_repo.get_by_contact = AsyncMock(
        return_value=journal_relationships or []
    )

    journal_repo = AsyncMock()
    if journals:
        journal_repo.find_by_id = AsyncMock(
            side_effect=lambda jid: next((j for j in journals if j.id == jid), None)
        )
    else:
        journal_repo.find_by_id = AsyncMock(return_value=None)

    journal_repo.get_types = AsyncMock(return_value=["NOTE"])

    summary_repo = AsyncMock()
    summary_repo.find_by_contact_id = AsyncMock(return_value=summary)

    return SummaryInputAssembler(
        contact_repo=contact_repo,
        history_repo=history_repo,
        journal_relationship_repo=journal_relationship_repo,
        journal_repo=journal_repo,
        summary_repo=summary_repo,
        series_repo=series_repo,
    )


@pytest.mark.unit
class TestSummaryInputAssembler:
    """Tests for SummaryInputAssembler."""

    @pytest.mark.asyncio
    async def test_assembles_contact_metadata(self):
        """Test that basic contact metadata is included in input."""
        assembler = _make_assembler()
        result = await assembler.assemble(contact_id=1)

        assert isinstance(result, SummaryInput)
        assert result.contact_name == "John Doe"
        assert result.company == "Acme"
        assert result.job_title == "Engineer"

    @pytest.mark.asyncio
    async def test_empty_contact_returns_minimal_input(self):
        """Test a contact with no activity returns minimal but valid input."""
        contact = Contact(first_name="Empty", id=1)
        assembler = _make_assembler(contact=contact)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert result.contact_name == "Empty"
        assert result.recent_notes == []
        assert result.recent_journals == []
        assert result.relationships == []
        assert result.recent_history == []

    @pytest.mark.asyncio
    async def test_includes_recent_notes(self):
        """Test that notes are included in assembled input."""
        notes = [
            ContactNote(content="A note about dinner", contact_id=1, id=1),
            ContactNote(content="Follow up on project", contact_id=1, id=2),
        ]
        contact = Contact(first_name="John", id=1, notes=notes)
        assembler = _make_assembler(contact=contact)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert len(result.recent_notes) == 2
        assert result.recent_notes[0] == "A note about dinner"

    @pytest.mark.asyncio
    async def test_respects_max_notes_limit(self):
        """Test that notes are capped at MAX_NOTES."""
        notes = [
            ContactNote(content=f"Note {i}", contact_id=1, id=i) for i in range(20)
        ]
        contact = Contact(first_name="John", id=1, notes=notes)
        assembler = _make_assembler(contact=contact)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert len(result.recent_notes) <= assembler.MAX_NOTES

    @pytest.mark.asyncio
    async def test_includes_relationships(self):
        """Contact-to-contact relationships name both parties and disclaim the user."""
        rels = [
            ContactRelationship(
                from_contact_id=1,
                to_contact_id=2,
                relationship_type=RelationshipType.FRIEND,
                from_contact_name="John Doe",
                to_contact_name="Jane Smith",
            ),
        ]
        contact = Contact(first_name="John", last_name="Doe", id=1, relationships=rels)
        assembler = _make_assembler(contact=contact)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert len(result.relationships) == 1
        rel = result.relationships[0]
        # Names both the contact and the other party, and clarifies it is NOT the user.
        assert "John Doe" in rel
        assert "Jane Smith" in rel
        assert "friend" in rel.lower()
        assert "not the user" in rel.lower()
        # Third-person only — "you"/"your" would refer to the AI assistant.
        assert "you" not in rel.lower()

    @pytest.mark.asyncio
    async def test_relationship_to_user_marked_as_user(self):
        """A to_user relationship is explicitly rendered as a relationship to the user."""
        rels = [
            ContactRelationship(
                from_contact_id=1,
                to_contact_id=None,
                relationship_type=RelationshipType.PARENT,
                from_contact_name="John Doe",
                to_user=True,
            ),
        ]
        contact = Contact(first_name="John", last_name="Doe", id=1, relationships=rels)
        assembler = _make_assembler(contact=contact)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert len(result.relationships) == 1
        rel = result.relationships[0].lower()
        assert "is the parent of the user" in rel
        assert "not the user" not in rel
        # Third-person only — never "you"/"your" (that is the AI assistant).
        assert "you" not in rel

    @pytest.mark.asyncio
    async def test_relationship_where_contact_is_target_is_inverted(self):
        """When the contact is the target side, use the other party and invert direction."""
        # Row: Mary (id=2) is the PARENT of John (id=1). Summarising John, the
        # rendered relationship must read that John is Mary's CHILD, not that John
        # is his own parent.
        rels = [
            ContactRelationship(
                from_contact_id=2,
                to_contact_id=1,
                relationship_type=RelationshipType.PARENT,
                from_contact_name="Mary Doe",
                to_contact_name="John Doe",
            ),
        ]
        contact = Contact(first_name="John", last_name="Doe", id=1, relationships=rels)
        assembler = _make_assembler(contact=contact)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert len(result.relationships) == 1
        rel = result.relationships[0]
        assert "Mary Doe" in rel
        assert "child" in rel.lower()
        assert "parent" not in rel.lower()
        assert "not the user" in rel.lower()

    @pytest.mark.asyncio
    async def test_includes_field_history(self):
        """Test that recent field history changes are included."""
        entries = [
            _make_history_entry("first_name", "John", "Jonathan"),
            _make_history_entry("company", None, "NewCo"),
        ]
        assembler = _make_assembler(history_entries=entries)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert len(result.recent_history) == 2

    @pytest.mark.asyncio
    async def test_respects_max_history_entries(self):
        """Test that history entries are capped at MAX_HISTORY_ENTRIES."""
        entries = [_make_history_entry(f"field_{i}") for i in range(30)]
        assembler = _make_assembler(history_entries=entries)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert len(result.recent_history) <= assembler.MAX_HISTORY_ENTRIES

    @pytest.mark.asyncio
    async def test_includes_recent_journals(self):
        """Test that linked journals are included via relationship repo."""
        j_rels = [
            _make_journal_relationship(journal_id=10),
            _make_journal_relationship(journal_id=20),
        ]
        journals = [
            _make_journal(10, "Lunch with John", "Great catch up"),
            _make_journal(20, "Project meeting", "Discussed roadmap"),
        ]
        assembler = _make_assembler(journal_relationships=j_rels, journals=journals)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert len(result.recent_journals) == 2

    @pytest.mark.asyncio
    async def test_respects_max_journals_limit(self):
        """Test that journals are capped at MAX_JOURNALS."""
        j_rels = [_make_journal_relationship(journal_id=i) for i in range(15)]
        journals = [_make_journal(i, f"Journal {i}") for i in range(15)]
        assembler = _make_assembler(journal_relationships=j_rels, journals=journals)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert len(result.recent_journals) <= assembler.MAX_JOURNALS

    @pytest.mark.asyncio
    async def test_splits_future_and_recent_journals(self):
        """Test that journals are correctly split into recent and future based on date."""
        from datetime import timedelta

        now = datetime.now(tz=UTC)
        past_date = now - timedelta(days=2)
        future_date = now + timedelta(days=2)

        j_rels = [
            _make_journal_relationship(journal_id=10),
            _make_journal_relationship(journal_id=20),
        ]
        journals = [
            _make_journal(10, "Past Event", "Happened already", start=past_date),
            _make_journal(20, "Future Event", "Will happen soon", start=future_date),
        ]

        assembler = _make_assembler(journal_relationships=j_rels, journals=journals)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert len(result.recent_journals) == 1
        assert len(result.future_journals) == 1

        assert result.recent_journals[0]["title"] == "Past Event"
        assert result.future_journals[0]["title"] == "Future Event"

    @pytest.mark.asyncio
    async def test_includes_previous_summary_when_available(self):
        """Test that the previous summary is included for incremental generation."""
        prev_summary = ContactSummary(
            contact_id=1,
            summary_text="Previous AI-generated summary about John.",
            status=SummaryStatus.GENERATED,
        )
        assembler = _make_assembler(summary=prev_summary)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert result.previous_summary == "Previous AI-generated summary about John."

    @pytest.mark.asyncio
    async def test_previous_summary_none_when_no_existing(self):
        """Test previous_summary is None on first-time generation."""
        assembler = _make_assembler(summary=None)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert result.previous_summary is None

    @pytest.mark.asyncio
    async def test_previous_summary_skipped_when_disabled(self):
        """Test previous summary with DISABLED status is not included."""
        prev_summary = ContactSummary(
            contact_id=1,
            summary_text="Old disabled text",
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.LOW_ACTIVITY,
        )
        assembler = _make_assembler(summary=prev_summary)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert result.previous_summary is None

    @pytest.mark.asyncio
    async def test_includes_important_dates(self):
        """Test that important dates are included in assembled input."""
        dates = [
            ImportantDate(
                contact_id=1,
                date_type=ImportantDateType.BIRTHDAY,
                precision=DatePrecision.DAY_MONTH,
                month=3,
                day=15,
            ),
        ]
        contact = Contact(first_name="John", id=1, important_dates=dates)
        assembler = _make_assembler(contact=contact)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert len(result.important_dates) == 1
        date_str = result.important_dates[0].lower()
        assert "birthday" in date_str
        # All date components should be present (not truncated)
        assert "month=3" in date_str
        assert "day=15" in date_str

    @pytest.mark.asyncio
    async def test_contact_not_found_returns_none(self):
        """Test that None is returned when contact doesn't exist."""
        contact_repo = AsyncMock()
        contact_repo.find_by_id = AsyncMock(return_value=None)
        assembler = SummaryInputAssembler(
            contact_repo=contact_repo,
            history_repo=AsyncMock(),
            journal_relationship_repo=AsyncMock(),
            journal_repo=AsyncMock(),
            summary_repo=AsyncMock(),
        )

        result = await assembler.assemble(contact_id=999)
        assert result is None


@pytest.mark.unit
class TestLongTermActivityStatistics:
    """Tests for long-term activity statistics computation."""

    @pytest.mark.asyncio
    async def test_computes_activity_buckets(self):
        """Test that long-term activity is bucketed by 12-month periods."""
        # Create journal relationships with dates spread across time
        now = datetime.now(tz=UTC)
        j_rels = []
        # 3 journals within 90 days (these go into recent, not stats)
        for i in range(3):
            rel = _make_journal_relationship(journal_id=i)
            rel.created_at = now - timedelta(days=30 + i)
            j_rels.append(rel)

        # 5 journals between 3-12 months ago
        for i in range(5):
            rel = _make_journal_relationship(journal_id=100 + i)
            rel.created_at = now - timedelta(days=120 + i * 30)
            j_rels.append(rel)

        # 2 journals between 12-24 months ago
        for i in range(2):
            rel = _make_journal_relationship(journal_id=200 + i)
            rel.created_at = now - timedelta(days=400 + i * 30)
            j_rels.append(rel)

        journals = [_make_journal(rel.journal_id) for rel in j_rels]
        assembler = _make_assembler(journal_relationships=j_rels, journals=journals)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert result.activity_stats is not None
        assert isinstance(result.activity_stats, list)
        # Should have buckets for older activity (beyond 90 days)
        assert len(result.activity_stats) > 0

    @pytest.mark.asyncio
    async def test_no_stats_when_no_old_activity(self):
        """Test that activity_stats is empty when all activity is recent."""
        now = datetime.now(tz=UTC)
        j_rels = [_make_journal_relationship(journal_id=1)]
        j_rels[0].created_at = now - timedelta(days=10)
        journals = [_make_journal(1)]

        assembler = _make_assembler(journal_relationships=j_rels, journals=journals)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert result.activity_stats == []

    @pytest.mark.asyncio
    async def test_stats_bucket_structure(self):
        """Test that activity stat buckets have the expected shape."""
        now = datetime.now(tz=UTC)
        # 1 journal 6 months ago (beyond 90-day window)
        rel = _make_journal_relationship(journal_id=1)
        rel.created_at = now - timedelta(days=200)
        journals = [_make_journal(1)]

        assembler = _make_assembler(journal_relationships=[rel], journals=journals)
        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert len(result.activity_stats) > 0
        bucket = result.activity_stats[0]
        assert isinstance(bucket, ActivityStatsBucket)
        assert isinstance(bucket.period_label, str)
        assert isinstance(bucket.event_count, int)
        assert bucket.event_count > 0


@pytest.mark.unit
class TestSummaryInputSeries:
    """Series membership is attached to assembled journal dicts."""

    @pytest.mark.asyncio
    async def test_assemble_populates_series_for_journals(self):
        """Journal dicts carry series names from one bulk lookup."""
        now = datetime.now(tz=UTC)
        journal = _make_journal(
            1, title="Physio session", start=now - timedelta(days=1)
        )
        journal.user_id = "user123"
        rel = _make_journal_relationship(journal_id=1)

        series_repo = AsyncMock()
        series_repo.get_series_names_for_journal_ids = AsyncMock(
            return_value={1: ["Physio appointments"]}
        )
        assembler = _make_assembler(
            journal_relationships=[rel],
            journals=[journal],
            series_repo=series_repo,
        )

        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert result.recent_journals[0]["series"] == ["Physio appointments"]
        series_repo.get_series_names_for_journal_ids.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_assemble_without_series_repo_defaults_to_empty(self):
        """Without a series repo, journal dicts carry no series names."""
        now = datetime.now(tz=UTC)
        journal = _make_journal(1, start=now - timedelta(days=1))
        rel = _make_journal_relationship(journal_id=1)
        assembler = _make_assembler(journal_relationships=[rel], journals=[journal])

        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert result.recent_journals[0]["series"] == []


@pytest.mark.unit
class TestSummaryInputSeriesLookupScope:
    """PR-review hardening: series are looked up only for retained journals."""

    @pytest.mark.asyncio
    async def test_series_lookup_only_covers_retained_journals(self):
        """Journals dropped by the recent-window filter don't feed the
        series bulk lookup."""
        now = datetime.now(tz=UTC)
        retained_journal = _make_journal(1, start=now - timedelta(days=1))
        retained_journal.user_id = "user123"
        retained_rel = _make_journal_relationship(journal_id=1)

        dropped_journal = _make_journal(2, start=now - timedelta(days=200))
        dropped_journal.user_id = "user123"
        dropped_rel = _make_journal_relationship(journal_id=2)
        dropped_rel.created_at = now - timedelta(days=200)  # outside window

        series_repo = AsyncMock()
        series_repo.get_series_names_for_journal_ids = AsyncMock(return_value={})
        assembler = _make_assembler(
            journal_relationships=[retained_rel, dropped_rel],
            journals=[retained_journal, dropped_journal],
            series_repo=series_repo,
        )

        result = await assembler.assemble(contact_id=1)

        assert result is not None
        assert len(result.recent_journals) == 1
        series_repo.get_series_names_for_journal_ids.assert_awaited_once_with(
            [1], "user123"
        )
