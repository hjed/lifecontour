"""Unit tests for LogbookPdfRenderer.

Tests PDF structure assertions using deterministic fixture data.
"""

import datetime
import io

import pytest
from core_shared.models.journals import (
    AbseilingData,
    AbseilPitch,
    CavingData,
    EventDateRange,
    FitnessData,
    GearMaintenanceData,
    KayakingData,
    LogbookEntryContact,
    LogbookEntryData,
    LogbookExportData,
    LogbookYearlySummary,
    OutdoorActivityData,
    ParticipantIndexEntry,
)

from app.core.journal.services.logbook_pdf_renderer import LogbookPdfRenderer

# ─── Fixture helpers ─────────────────────────────────────────────────


def _make_date_range(year: int = 2024, month: int = 1, day: int = 15) -> EventDateRange:
    """Create an EventDateRange for a given date."""
    dt = datetime.datetime(year, month, day, tzinfo=datetime.UTC)
    return EventDateRange(start=dt, end=dt)


def _make_entry(
    entry_id: int,
    title: str = "Test Entry",
    content: str = "Some content",
    types: list[str] | None = None,
    parent_id: int | None = None,
    year: int = 2024,
    month: int = 1,
    day: int = 15,
) -> LogbookEntryData:
    """Create a minimal LogbookEntryData for testing."""
    return LogbookEntryData(
        id=entry_id,
        title=title,
        content=content,
        event_date_range=_make_date_range(year, month, day),
        parent_id=parent_id,
        journal_types=types or ["BUSHWALKING"],
    )


def _make_entry_with_outdoor_data(
    entry_id: int,
    title: str = "Bushwalking Trip",
    in_leadership: bool = False,
) -> LogbookEntryData:
    """Create an entry with outdoor activity data."""
    entry = _make_entry(entry_id, title=title, types=["BUSHWALKING"])
    entry.outdoor_activity_data = OutdoorActivityData(
        journal_id=entry_id,
        weather_conditions="Sunny and warm",
        role="Leader" if in_leadership else "Participant",
        in_leadership_role=in_leadership,
        participant_notes="Brought extra water",
    )
    return entry


def _make_entry_with_pitches(entry_id: int) -> LogbookEntryData:
    """Create an entry with abseil pitch data."""
    entry = _make_entry(entry_id, title="Canyoning at Claustral", types=["CANYONING"])
    entry.abseiling_data = AbseilingData(
        journal_id=entry_id,
        number_of_abseils=3,
        total_length=60,
        number_of_setups=2,
        number_of_rescues=1,
    )
    entry.abseil_pitches = [
        AbseilPitch(
            id=100,
            journal_id=entry_id,
            pitch_number=1,
            height=25,
            anchor_location="TL",
            anchor_type="chains",
            did_rescue=False,
            did_setup=True,
        ),
        AbseilPitch(
            id=101,
            journal_id=entry_id,
            pitch_number=2,
            height=15,
            anchor_location="Centre",
            anchor_type="double bolt",
            did_rescue=True,
            did_setup=True,
        ),
        AbseilPitch(
            id=102,
            journal_id=entry_id,
            pitch_number=3,
            height=20,
            anchor_location="TR",
            anchor_type="sling on tree",
            did_rescue=False,
            did_setup=False,
        ),
    ]
    return entry


def _make_entry_with_fitness(entry_id: int) -> LogbookEntryData:
    """Create an entry with fitness data."""
    entry = _make_entry(entry_id, title="Morning Bushwalk", types=["BUSHWALKING"])
    entry.fitness_data = FitnessData(
        journal_id=entry_id,
        distance=12500,  # 12.5km in metres
        elevation_gain=450,
        duration=10800,  # 180 minutes in seconds
        heart_rate_avg=130,
        heart_rate_max=165,
        calories=850,
    )
    return entry


def _make_entry_with_contacts(entry_id: int) -> LogbookEntryData:
    """Create an entry with contact participants."""
    entry = _make_entry(entry_id, title="Group Bushwalk", types=["BUSHWALKING"])
    entry.contacts = [
        LogbookEntryContact(contact_id=1, name="Alice Smith", role="PARTICIPANT"),
        LogbookEntryContact(contact_id=2, name="Bob Jones", role="INVITEE"),
    ]
    return entry


def _make_entry_with_template_and_gear(entry_id: int) -> LogbookEntryData:
    """Create an entry with template and gear item references."""
    import uuid

    entry = _make_entry(
        entry_id, title="Gear Maintenance Log", types=["GEAR_MAINTENANCE"]
    )
    entry.template_name = "Claustral Canyon"
    entry.gear_item_name = "10mm Static Rope"
    entry.gear_maintenance_data = GearMaintenanceData(
        journal_id=entry_id,
        gear_item_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        maintenance_type="routine inspection",
    )
    return entry


def _make_entry_with_template_reference(
    entry_id: int, template_name: str = "Empress Falls"
) -> LogbookEntryData:
    """Create an abseiling-derived entry that references a template."""
    entry = _make_entry(
        entry_id, title="Abseil From Template", types=["ABSEILING_TRIP"]
    )
    entry.template_name = template_name
    return entry


def _make_hierarchical_data() -> LogbookExportData:
    """Create data with parent-child hierarchy."""
    parent = _make_entry(1, title="Blue Mountains Weekend", types=["NOTE"])
    child1 = _make_entry(2, title="Saturday Bushwalk", types=["BUSHWALKING"])
    child1.parent_id = 1
    child2 = _make_entry(3, title="Sunday Canyoning", types=["CANYONING"])
    child2.parent_id = 1
    parent.children = [child1, child2]

    return LogbookExportData(
        entries=[parent],
        yearly_summaries=[],
        participant_index=[],
    )


def _make_rich_export_data() -> LogbookExportData:
    """Create a rich export data set with summaries and participant index."""
    entries = [
        _make_entry_with_outdoor_data(1, "Leadership Walk", in_leadership=True),
        _make_entry_with_pitches(2),
        _make_entry_with_fitness(3),
        _make_entry_with_contacts(4),
        _make_entry_with_template_and_gear(5),
    ]

    summaries = [
        LogbookYearlySummary(
            year=2024,
            total_activities_by_type={"BUSHWALKING": 15, "CANYONING": 8},
            leadership_activities_by_type={"BUSHWALKING": 5, "CANYONING": 3},
            total_abseiling_metres=480,
            total_abseils=32,
            total_setups=12,
            total_rescues=2,
        ),
    ]

    participant_index = [
        ParticipantIndexEntry(contact_id=1, name="Alice Smith", appearances=12),
        ParticipantIndexEntry(contact_id=2, name="Bob Jones", appearances=8),
        ParticipantIndexEntry(contact_id=3, name="Charlie Brown", appearances=5),
    ]

    return LogbookExportData(
        entries=entries,
        yearly_summaries=summaries,
        participant_index=participant_index,
    )


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pypdf.

    Returns the concatenated text from all pages.
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n".join(parts)


def _internal_link_target_pages(pdf_bytes: bytes) -> list[int | None]:
    """Resolve every intra-document link annotation to its target page index.

    ReportLab renders ``<a href="#anchor">`` links as ``/Link`` annotations
    carrying an explicit ``/Dest`` array whose first element references the
    destination page. External ``/URI`` links have no ``/Dest`` and are
    ignored. Returns one entry per internal link: the 0-based index of the
    page it points to, or ``None`` when the target cannot be resolved.
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_idnums = {
        page.indirect_reference.idnum: idx
        for idx, page in enumerate(reader.pages)
        if page.indirect_reference is not None
    }
    targets: list[int | None] = []
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            obj = annot.get_object()
            if obj.get("/Subtype") != "/Link" or "/Dest" not in obj:
                continue
            dest = obj["/Dest"]
            if isinstance(dest, list) and dest and hasattr(dest[0], "idnum"):
                targets.append(page_idnums.get(dest[0].idnum))
            else:
                targets.append(None)
    return targets


# ─── Test class ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestLogbookPdfRenderer:
    """Tests for the LogbookPdfRenderer."""

    def _renderer(self) -> LogbookPdfRenderer:
        return LogbookPdfRenderer()

    # ── Basic PDF validity ─────────────────────────────────────

    def test_render_empty_logbook(self) -> None:
        """Empty entries list produces a valid PDF with cover page."""
        data = LogbookExportData(entries=[], yearly_summaries=[], participant_index=[])
        result = self._renderer().render(data)
        assert isinstance(result, bytes)
        assert len(result) > 0
        assert result[:5] == b"%PDF-"

    def test_render_produces_valid_pdf(self) -> None:
        """Output bytes start with PDF header."""
        data = LogbookExportData(
            entries=[_make_entry(1)],
            yearly_summaries=[],
            participant_index=[],
        )
        result = self._renderer().render(data)
        assert result[:5] == b"%PDF-"

    # ── Cover page ─────────────────────────────────────────────

    def test_cover_page_present(self) -> None:
        """PDF text contains the outdoor logbook title."""
        data = LogbookExportData(
            entries=[_make_entry(1)],
            yearly_summaries=[],
            participant_index=[],
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Outdoor Logbook" in text

    # ── Journal entries ────────────────────────────────────────

    def test_journal_entries_rendered(self) -> None:
        """PDF text contains journal titles from fixture data."""
        entries = [
            _make_entry(1, title="Morning Bushwalk"),
            _make_entry(2, title="Afternoon Canyon Trip"),
        ]
        data = LogbookExportData(
            entries=entries, yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Morning Bushwalk" in text
        assert "Afternoon Canyon Trip" in text

    def test_journal_content_rendered(self) -> None:
        """PDF text contains journal content."""
        entry = _make_entry(1, title="Test", content="Detailed trip notes here")
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Detailed trip notes here" in text

    def test_hierarchy_indentation(self) -> None:
        """Child entries appear in the PDF output."""
        data = _make_hierarchical_data()
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Blue Mountains Weekend" in text
        assert "Saturday Bushwalk" in text
        assert "Sunday Canyoning" in text

    # ── Type-specific data ─────────────────────────────────────

    def test_outdoor_activity_data_rendered(self) -> None:
        """Outdoor activity fields appear in PDF output."""
        entry = _make_entry_with_outdoor_data(1, "Sunny Walk", in_leadership=True)
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Sunny" in text
        assert "Leader" in text
        assert "leadership" in text.lower()

    def test_type_specific_data_rendered(self) -> None:
        """Various type-specific data sections appear in the PDF."""
        # Create entries with different type-specific data
        kayaking_entry = _make_entry(10, title="River Paddle", types=["KAYAKING"])
        kayaking_entry.kayaking_data = KayakingData(
            journal_id=10,
            is_white_water=True,
            rapids_grade="III",
        )

        caving_entry = _make_entry(11, title="Cave Exploration", types=["CAVING"])
        caving_entry.caving_data = CavingData(
            journal_id=11,
            is_vertical=True,
            is_horizontal=False,
        )

        data = LogbookExportData(
            entries=[kayaking_entry, caving_entry],
            yearly_summaries=[],
            participant_index=[],
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "River Paddle" in text
        assert "Cave Exploration" in text

    # ── Abseil pitches ─────────────────────────────────────────

    def test_abseil_pitch_table_rendered(self) -> None:
        """Pitch data appears in the PDF output."""
        entry = _make_entry_with_pitches(1)
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        # Pitch heights should appear
        assert "25" in text
        assert "15" in text
        assert "20" in text
        # Anchor types should appear
        assert "chains" in text
        # Setup/Rescue columns should appear (pitches have explicit values)
        assert "Setup" in text
        assert "Rescue" in text

    def test_pitch_table_omits_columns_when_all_none(self) -> None:
        """Setup/Rescue columns are omitted when all pitches have None."""
        entry = _make_entry(1, title="Basic Abseil", types=["CANYONING"])
        entry.abseil_pitches = [
            AbseilPitch(
                journal_id=1,
                pitch_number=1,
                height=10,
                anchor_type="chains",
                did_setup=None,
                did_rescue=None,
            ),
            AbseilPitch(
                journal_id=1,
                pitch_number=2,
                height=15,
                anchor_type="double bolt",
                did_setup=None,
                did_rescue=None,
            ),
        ]
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "10" in text
        assert "15" in text
        assert "Setup" not in text
        assert "Rescue" not in text

    def test_pitch_table_includes_column_when_partial_none(self) -> None:
        """Setup column included when some pitches have values and others None."""
        entry = _make_entry(1, title="Partial Setup", types=["CANYONING"])
        entry.abseil_pitches = [
            AbseilPitch(
                journal_id=1,
                pitch_number=1,
                height=10,
                anchor_type="chains",
                did_setup=True,
                did_rescue=None,
            ),
            AbseilPitch(
                journal_id=1,
                pitch_number=2,
                height=15,
                anchor_type="double bolt",
                did_setup=None,
                did_rescue=None,
            ),
        ]
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        # Setup column should be present because pitch 1 has a value
        assert "Setup" in text
        # Rescue column should be omitted because all are None
        assert "Rescue" not in text

    # ── Fitness data ───────────────────────────────────────────

    def test_fitness_data_rendered(self) -> None:
        """Fitness metrics appear in the PDF output."""
        entry = _make_entry_with_fitness(1)
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "12500" in text  # distance in metres
        assert "450" in text  # elevation_gain
        assert "10800" in text  # duration in seconds

    # ── Contacts ───────────────────────────────────────────────

    def test_contacts_rendered(self) -> None:
        """Contact names with roles appear in the PDF output."""
        entry = _make_entry_with_contacts(1)
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Alice Smith" in text
        assert "Bob Jones" in text

    # ── Template and gear names ────────────────────────────────

    def test_template_and_gear_names_rendered(self) -> None:
        """Template and gear item names appear when present."""
        entry = _make_entry_with_template_and_gear(1)
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Based on:" in text
        assert "Claustral Canyon" in text
        assert "10mm Static Rope" in text

    def test_template_reference_rendered_for_abseiling_entry(self) -> None:
        """The 'Based on: <template>' reference renders for abseiling-derived types."""
        entry = _make_entry_with_template_reference(1, template_name="Empress Falls")
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Based on:" in text
        assert "Empress Falls" in text

    def test_template_reference_omitted_when_absent(self) -> None:
        """No 'Based on:' line is rendered when the entry has no template name."""
        entry = _make_entry(
            1, title="Abseil Without Template", types=["ABSEILING_TRIP"]
        )
        assert entry.template_name is None
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Based on:" not in text

    # ── Immich photo album shared link ─────────────────────────

    def test_photo_album_link_rendered_when_present(self) -> None:
        """The album shared link is rendered after the participants line."""
        entry = _make_entry(1, title="Trip With Photos")
        entry.album_shared_link = "https://immich.example.com/share/abc123"
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Photo Album:" in text
        assert "https://immich.example.com/share/abc123" in text

    def test_photo_album_link_absent_when_none(self) -> None:
        """No album link line is rendered when there is no shared link."""
        entry = _make_entry(1, title="Trip Without Photos")
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Photo Album:" not in text

    # ── Yearly summaries ───────────────────────────────────────

    def test_yearly_summary_rendered(self) -> None:
        """Summary statistics appear in the PDF output."""
        data = _make_rich_export_data()
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "2024" in text
        assert "480" in text  # total_abseiling_metres
        assert "32" in text  # total_abseils

    # ── Participant index ──────────────────────────────────────

    def test_participant_index_rendered(self) -> None:
        """Participant names and appearance counts appear in the PDF."""
        data = _make_rich_export_data()
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Alice Smith" in text
        assert "Bob Jones" in text
        assert "Charlie Brown" in text
        assert "12" in text  # Alice's appearances
        assert "8" in text  # Bob's appearances

    # ── Performance ────────────────────────────────────────────

    def test_large_logbook_performance(self) -> None:
        """500 entries should render within 30 seconds without memory error."""
        entries = []
        for i in range(500):
            entry = _make_entry(
                i + 1,
                title=f"Activity {i + 1}",
                content=f"Details for activity {i + 1}",
                types=["BUSHWALKING"],
                year=2020 + (i % 5),
                month=(i % 12) + 1,
                day=(i % 28) + 1,
            )
            if i % 10 == 0:
                entry.fitness_data = FitnessData(
                    journal_id=i + 1,
                    distance=i * 1000,
                    elevation_gain=i * 10,
                    duration=i * 180,
                )
            entries.append(entry)

        data = LogbookExportData(
            entries=entries,
            yearly_summaries=[
                LogbookYearlySummary(
                    year=y,
                    total_activities_by_type={"BUSHWALKING": 100},
                    total_abseiling_metres=1000,
                    total_abseils=50,
                )
                for y in range(2020, 2025)
            ],
            participant_index=[
                ParticipantIndexEntry(
                    contact_id=c, name=f"Contact {c}", appearances=c * 2
                )
                for c in range(1, 20)
            ],
        )

        result = self._renderer().render(data)

        assert isinstance(result, bytes)
        assert result[:5] == b"%PDF-"

    # ── Date rendering ─────────────────────────────────────────

    def test_entry_date_rendered(self) -> None:
        """Journal entry dates appear in the PDF."""
        entry = _make_entry(1, title="Dated Entry", year=2024, month=3, day=15)
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        # Should contain the date in some format
        assert "15" in text
        assert "2024" in text

    # ── Journal types badge ────────────────────────────────────

    def test_journal_types_rendered(self) -> None:
        """Journal type labels appear in the PDF."""
        entry = _make_entry(1, title="Multi Type", types=["BUSHWALKING", "FITNESS"])
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Bushwalking" in text

    # ── Navigation: summary-first + table of contents + anchors ─

    def test_summary_precedes_entries(self) -> None:
        """Yearly summaries render before the journal entries (spec 3.1)."""
        data = _make_rich_export_data()
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        # Both the summaries section and the first entry are present...
        assert "Yearly Summaries" in text
        assert "Leadership Walk" in text
        # ...and the summary precedes the entry SECTION. The entry title now
        # also appears in the TOC (which follows the summary), so we anchor the
        # ordering on entry-body text that only appears in the section itself.
        assert "Weather: Sunny and warm" in text
        assert text.index("Yearly Summaries") < text.index("Weather: Sunny and warm")

    def test_table_of_contents_present(self) -> None:
        """A table of contents lists the major sections (spec 3.2)."""
        data = _make_rich_export_data()
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Contents" in text
        # The TOC lists the summary, a top-level trip, and the indexes.
        assert "Summary" in text
        assert "Participant Index" in text
        # The TOC precedes the entry SECTIONS it links to. Anchor on entry-body
        # text (absent from the TOC) so the check targets the section, not the
        # entry's own TOC row.
        assert text.index("Contents") < text.index("Weather: Sunny and warm")

    def test_toc_internal_links_resolve(self) -> None:
        """Every TOC row is an internal link that resolves to a real page.

        The TOC has exactly one row per major section — summary, each top-level
        trip, and the participant index — so a dropped row would change the
        count. Combined with the all-resolve check this locks in that every
        expected link is present and points to a live destination.
        """
        data = _make_rich_export_data()
        result = self._renderer().render(data)
        targets = _internal_link_target_pages(result)
        expected = 1 + len(data.entries) + 1  # summary + trips + participant index
        assert len(targets) == expected
        assert all(t is not None for t in targets)

    def test_entry_has_stable_anchor(self) -> None:
        """A trip's TOC link jumps to the page that actually contains the trip.

        Uses a single top-level entry so the entry link is unambiguous: link
        order is [summary, entry], and the entry link must resolve to a page
        whose text contains the entry title. This proves the ``entry_{id}``
        anchor is real and correctly targeted (not merely that some link
        resolves somewhere).
        """
        from pypdf import PdfReader

        entry = _make_entry(42, title="Solo Ridge Traverse", types=["BUSHWALKING"])
        summary = LogbookYearlySummary(
            year=2024,
            total_activities_by_type={"BUSHWALKING": 1},
            total_abseiling_metres=0,
            total_abseils=0,
        )
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[summary], participant_index=[]
        )
        result = self._renderer().render(data)

        targets = _internal_link_target_pages(result)
        # Exactly the summary link and the single entry link.
        assert len(targets) == 2
        assert all(t is not None for t in targets)

        reader = PdfReader(io.BytesIO(result))
        entry_link_page = targets[1]
        assert entry_link_page is not None
        entry_page_text = reader.pages[entry_link_page].extract_text()
        assert "Solo Ridge Traverse" in entry_page_text

    def test_toc_absent_for_empty_logbook(self) -> None:
        """An empty logbook renders no table of contents."""
        data = LogbookExportData(entries=[], yearly_summaries=[], participant_index=[])
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Contents" not in text
        assert _internal_link_target_pages(result) == []
