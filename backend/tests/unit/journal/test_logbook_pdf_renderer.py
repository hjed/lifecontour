"""Unit tests for LogbookPdfRenderer.

Tests PDF structure assertions using deterministic fixture data.
"""

import dataclasses
import datetime
import io

import pytest
from core_shared.models.journals import (
    JOURNAL_TYPE_GLYPHS,
    AbseilingData,
    AbseilPitch,
    ActivityTypeIndexEntry,
    CavingData,
    EventDateRange,
    FitnessData,
    GearMaintenanceData,
    JournalType,
    KayakingData,
    LogbookEntryContact,
    LogbookEntryData,
    LogbookExportData,
    LogbookIndexJournal,
    LogbookYearlySummary,
    OutdoorActivityData,
    ParticipantIndexEntry,
)
from PIL import Image
from reportlab.lib.units import mm

from app.core.journal.services.logbook_pdf_renderer import (
    LogbookPdfRenderer,
    glyph_font_name,
    resolve_glyph_font_path,
)
from tests.pdf_assertions import (
    embedded_image_bytes,
    embedded_image_x_offsets,
    external_link_uris,
)

# ─── Fixture helpers ─────────────────────────────────────────────────


def _map_png(size: tuple[int, int] = (256, 192)) -> bytes:
    """Return PNG bytes standing in for a rendered GPX map image.

    The renderer only embeds what it is handed, so composing a real basemap is
    the map renderer's job (and its own tests'); here any decodable image will
    do.
    """
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 210, 220)).save(buffer, format="PNG")
    return buffer.getvalue()


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


def _make_deep_hierarchy_data() -> LogbookExportData:
    """Create data three levels deep (trip → day → activity)."""
    grandchild = _make_entry(3, title="Afternoon Abseil", types=["ABSEILING_TRIP"])
    grandchild.parent_id = 2
    child = _make_entry(2, title="Saturday", types=["BUSHWALKING"])
    child.parent_id = 1
    child.children = [grandchild]
    parent = _make_entry(1, title="Kanangra Weekend", types=["NOTE"])
    parent.children = [child]

    return LogbookExportData(
        entries=[parent],
        yearly_summaries=[],
        participant_index=[],
    )


def _make_summary(year: int) -> LogbookYearlySummary:
    """Create a minimal yearly summary for a given year."""
    return LogbookYearlySummary(
        year=year,
        total_activities_by_type={"BUSHWALKING": 1},
        leadership_activities_by_type={},
        total_abseiling_metres=0,
        total_abseils=0,
        total_setups=0,
        total_rescues=0,
    )


def _make_two_year_summary_data() -> LogbookExportData:
    """Create data whose summary section spans two years.

    Years are newest-first, matching the order ``LogbookSummaryCalculator``
    produces, so the navigation order asserted here is the real one.
    """
    return LogbookExportData(
        entries=[_make_entry(1, title="Ridge Walk", types=["BUSHWALKING"])],
        yearly_summaries=[_make_summary(2025), _make_summary(2024)],
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


def _make_indexed_export_data() -> LogbookExportData:
    """Export data whose indexes reference the entries they list.

    Three entries across three types, one of them (the canyon trip) carrying
    two type rows, plus a participant who appears in all three — enough to
    exercise both index sections and their internal links.
    """
    walk = _make_entry(1, title="Ridge Walk", types=["BUSHWALKING"], day=1)
    canyon = _make_entry(
        2, title="Claustral Canyon", types=["CANYONING", "BUSHWALKING"], day=2
    )
    cave = _make_entry(3, title="Jenolan Caves", types=["CAVING"], day=3)

    refs = {
        entry.id: LogbookIndexJournal(journal_id=entry.id, title=entry.title)
        for entry in (walk, canyon, cave)
    }

    return LogbookExportData(
        entries=[walk, canyon, cave],
        yearly_summaries=[],
        participant_index=[
            ParticipantIndexEntry(
                contact_id=1,
                name="Alice Smith",
                appearances=3,
                journals=[refs[1], refs[2], refs[3]],
            )
        ],
        activity_type_index=[
            ActivityTypeIndexEntry(
                activity_type="BUSHWALKING", journals=[refs[1], refs[2]]
            ),
            ActivityTypeIndexEntry(activity_type="CANYONING", journals=[refs[2]]),
            ActivityTypeIndexEntry(activity_type="CAVING", journals=[refs[3]]),
        ],
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


def _internal_link_destinations(pdf_bytes: bytes) -> list[tuple[int, str, str]]:
    """Resolve every internal link to its exact destination, in document order.

    ReportLab writes ``<a href="#x">`` as a ``/Link`` annotation whose ``/Dest``
    is ``[page, '/XYZ', x, y, zoom]``, where the coordinates are those of the
    anchored paragraph. Returning the page *with* those coordinates identifies
    which anchor a link points at — resolving only to a page cannot tell two
    entries apart when they share one, which in these fixtures they always do.

    Annotations are read page by page in emission order, so the result follows
    document order: the contents rows first, then each index section's links.
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_idnums = {
        page.indirect_reference.idnum: idx
        for idx, page in enumerate(reader.pages)
        if page.indirect_reference is not None
    }

    destinations: list[tuple[int, str, str]] = []
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            obj = annot.get_object()
            if obj.get("/Subtype") != "/Link" or "/Dest" not in obj:
                continue
            dest = obj["/Dest"]
            assert isinstance(dest, list) and hasattr(dest[0], "idnum"), dest
            page_index = page_idnums[dest[0].idnum]
            destinations.append((page_index, str(dest[2]), str(dest[3])))
    return destinations


def _entry_destinations(
    pdf_bytes: bytes, data: LogbookExportData
) -> tuple[dict[int, tuple[int, str, str]], int]:
    """Map each entry id to its anchor's destination, via the contents rows.

    The contents page holds exactly one row per navigable section, emitted
    before any index links, so its rows give a trustworthy reference for where
    each entry's anchor actually lives. Returns that mapping plus the number of
    contents rows, so a caller can slice the index links that follow.
    """
    destinations = _internal_link_destinations(pdf_bytes)
    toc_rows = (
        len(data.entries)
        + bool(data.yearly_summaries) * (1 + len(data.yearly_summaries))
        + bool(data.participant_index)
        + bool(data.activity_type_index)
    )

    # Entry rows follow the summary rows and precede the index rows.
    first_entry_row = bool(data.yearly_summaries) * (1 + len(data.yearly_summaries))
    entry_rows = destinations[first_entry_row : first_entry_row + len(data.entries)]
    return {
        entry.id: destination
        for entry, destination in zip(data.entries, entry_rows, strict=True)
    }, toc_rows


@dataclasses.dataclass
class _OutlineNode:
    """A single PDF outline (bookmark) entry and its nested children."""

    title: str
    page: int | None
    children: list[_OutlineNode]


def _outline_tree(pdf_bytes: bytes) -> list[_OutlineNode]:
    """Read the PDF document outline as a tree of title/page/children nodes.

    ``pypdf`` returns the outline as a flat list in which a nested list follows
    the entry it belongs to. This rebuilds that into an explicit tree and
    resolves each bookmark's destination page to a 0-based page index using the
    same object-number mapping as ``_internal_link_target_pages``.
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_idnums = {
        page.indirect_reference.idnum: idx
        for idx, page in enumerate(reader.pages)
        if page.indirect_reference is not None
    }

    def _page_index(destination: object) -> int | None:
        raw = destination.raw_get("/Page")  # type: ignore[attr-defined]
        idnum = getattr(raw, "idnum", None)
        if idnum is None:
            idnum = getattr(getattr(raw, "indirect_reference", None), "idnum", None)
        return page_idnums.get(idnum) if idnum is not None else None

    def _convert(items: list[object]) -> list[_OutlineNode]:
        nodes: list[_OutlineNode] = []
        for item in items:
            if isinstance(item, list):
                assert nodes, "nested outline entries without a parent entry"
                nodes[-1].children = _convert(item)
            else:
                nodes.append(
                    _OutlineNode(
                        title=str(item.title),  # type: ignore[attr-defined]
                        page=_page_index(item),
                        children=[],
                    )
                )
        return nodes

    return _convert(list(reader.outline))


def _outline_titles(nodes: list[_OutlineNode]) -> list[str]:
    """Return the titles of a list of outline nodes."""
    return [node.title for node in nodes]


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

    # ── Immich photo album shared links (spec 3.5) ─────────────

    def test_photo_album_link_rendered_when_present(self) -> None:
        """The album shared link is rendered after the participants line."""
        entry = _make_entry(1, title="Trip With Photos")
        entry.album_shared_links = ["https://immich.example.com/share/abc123"]
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Photo Album:" in text
        assert "https://immich.example.com/share/abc123" in text
        assert external_link_uris(result) == ["https://immich.example.com/share/abc123"]

    def test_photo_album_links_rendered_for_every_album(self) -> None:
        """Every album on an entry gets its own clickable link, in order."""
        entry = _make_entry(1, title="Trip With Two Albums")
        entry.album_shared_links = [
            "https://immich.example.com/share/first",
            "https://immich.example.com/share/second",
        ]
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)

        text = _extract_pdf_text(result)
        assert text.count("Photo Album:") == 2
        assert external_link_uris(result) == entry.album_shared_links

    def test_photo_album_link_url_with_quote_is_escaped(self) -> None:
        """A quote in the share URL cannot break the href attribute.

        The URL is interpolated into ``href="…"``; ``_safe_str`` alone does not
        escape quotes, so an unescaped ``"`` would close the attribute early and
        corrupt (or fail) the link. The link must still resolve to the exact URL.
        """
        url = 'https://immich.example.com/share/a"b?x="y"'
        entry = _make_entry(1, title="Trip With Tricky Url")
        entry.album_shared_links = [url]
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )

        result = self._renderer().render(data)

        assert result[:5] == b"%PDF-"
        assert external_link_uris(result) == [url]

    def test_photo_album_link_absent_when_none(self) -> None:
        """No album link line is rendered when there is no shared link."""
        entry = _make_entry(1, title="Trip Without Photos")
        assert entry.album_shared_links == []
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Photo Album:" not in text
        assert external_link_uris(result) == []

    # ── GPX track maps (spec 3.6) ──────────────────────────────

    def test_map_image_flowable_rendered_when_supplied(self) -> None:
        """A supplied map image is embedded as a real image in the PDF."""
        entry = _make_entry(1, title="Trip With A Track")
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )

        result = self._renderer().render(data, map_images={1: _map_png()})

        assert [len(image) > 0 for image in embedded_image_bytes(result)] == [True]

    def test_no_embedded_image_when_no_maps_supplied(self) -> None:
        """Without a map, the entry carries no image at all (spec §3.6).

        The type icons are font glyphs rather than pictures, so the logbook PDF
        has no other raster content and this count can be exact.
        """
        entry = _make_entry(1, title="Trip Without A Track")
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )

        result = self._renderer().render(data)

        assert embedded_image_bytes(result) == []

    def test_map_image_only_for_entries_with_a_map(self) -> None:
        """Only the entry that has a map gets one."""
        data = LogbookExportData(
            entries=[_make_entry(1, title="Mapped"), _make_entry(2, title="Unmapped")],
            yearly_summaries=[],
            participant_index=[],
        )

        result = self._renderer().render(data, map_images={1: _map_png()})

        assert len(embedded_image_bytes(result)) == 1

    def test_child_entry_map_image_rendered(self) -> None:
        """Maps reach child activities, not just root entries."""
        child = _make_entry(2, title="Day Two", parent_id=1)
        parent = _make_entry(1, title="Multi-Day Trip")
        parent.children = [child]
        data = LogbookExportData(
            entries=[parent], yearly_summaries=[], participant_index=[]
        )

        result = self._renderer().render(data, map_images={2: _map_png()})

        assert len(embedded_image_bytes(result)) == 1

    def test_map_image_aligns_with_its_entry_indentation(self) -> None:
        """The map lands at the entry's own indent, not centred on the page.

        Asserting the drawn x-offset rather than mere presence: the map sits in
        a wrapping ``Table``, whose ``hAlign`` defaults to ``CENTER``, so an
        implicit default would silently centre it and no presence-only test
        would notice.
        """
        child = _make_entry(2, title="Day Two", parent_id=1)
        parent = _make_entry(1, title="Multi-Day Trip")
        parent.children = [child]
        data = LogbookExportData(
            entries=[parent], yearly_summaries=[], participant_index=[]
        )
        renderer = self._renderer()

        on_root = renderer.render(data, map_images={1: _map_png()})
        on_child = renderer.render(data, map_images={2: _map_png()})

        # Entry bodies are indented 4mm, and each depth adds a further 10mm.
        assert embedded_image_x_offsets(on_root) == [pytest.approx(4 * mm)]
        assert embedded_image_x_offsets(on_child) == [pytest.approx(14 * mm)]

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

        The TOC has exactly one row per major section — summary, each year
        within it, each top-level trip, and the participant index — so a
        dropped row would change the count. Combined with the all-resolve
        check this locks in that every expected link is present and points to
        a live destination.
        """
        data = _make_rich_export_data()
        result = self._renderer().render(data)
        targets = _internal_link_target_pages(result)
        # summary + one row per year + trips + participant index
        expected = 1 + len(data.yearly_summaries) + len(data.entries) + 1
        assert len(targets) == expected
        assert all(t is not None for t in targets)

    def test_toc_lists_summary_years(self) -> None:
        """The contents page lists each year of the summary as a linked row."""
        data = _make_two_year_summary_data()
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)

        assert "Contents" in text
        assert "Year 2025" in text
        assert "Year 2024" in text

        targets = _internal_link_target_pages(result)
        # summary + two years + the single trip (no participant index)
        assert len(targets) == 4
        assert all(t is not None for t in targets)

    def test_entry_has_stable_anchor(self) -> None:
        """A trip's TOC link jumps to the page that actually contains the trip.

        Uses a single top-level entry so the entry link is unambiguous: link
        order is [summary, year, entry], and the entry link must resolve to a
        page whose text contains the entry title. This proves the
        ``entry_{id}`` anchor is real and correctly targeted (not merely that
        some link resolves somewhere).
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
        # Exactly the summary link, its single year link, and the entry link.
        assert len(targets) == 3
        assert all(t is not None for t in targets)

        reader = PdfReader(io.BytesIO(result))
        entry_link_page = targets[2]
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

    # ── Document outline / bookmarks (spec 3.7) ────────────────

    def test_document_outline_top_level_mirrors_toc(self) -> None:
        """The outline's top level mirrors the contents page (spec 3.7)."""
        data = _make_rich_export_data()
        result = self._renderer().render(data)

        outline = _outline_tree(result)
        assert _outline_titles(outline) == [
            "Summary",
            *[entry.title for entry in data.entries],
            "Participant Index",
        ]
        assert all(node.page is not None for node in outline)

    def test_outline_nests_summary_years(self) -> None:
        """Each year of the summary is nested under the Summary entry."""
        data = _make_two_year_summary_data()
        result = self._renderer().render(data)

        outline = _outline_tree(result)
        assert _outline_titles(outline) == ["Summary", "Ridge Walk"]
        assert _outline_titles(outline[0].children) == ["Year 2025", "Year 2024"]

    def test_outline_nests_child_activities(self) -> None:
        """Child activities nest under their parent trip in the outline.

        They are deliberately *not* listed on the contents page, which stays a
        list of major sections (spec 3.2) — so the parent trip is the only TOC
        row here, and each child title appears once, in the entry body.
        """
        data = _make_hierarchical_data()
        result = self._renderer().render(data)

        outline = _outline_tree(result)
        assert _outline_titles(outline) == ["Blue Mountains Weekend"]
        assert _outline_titles(outline[0].children) == [
            "Saturday Bushwalk",
            "Sunday Canyoning",
        ]

        # One TOC row (the parent trip) — the children add no contents rows.
        assert len(_internal_link_target_pages(result)) == 1
        assert _extract_pdf_text(result).count("Saturday Bushwalk") == 1

    def test_outline_nests_grandchild_activities(self) -> None:
        """The outline nests the full journal hierarchy, not just one level."""
        data = _make_deep_hierarchy_data()
        result = self._renderer().render(data)

        outline = _outline_tree(result)
        assert _outline_titles(outline) == ["Kanangra Weekend"]
        child = outline[0].children[0]
        assert child.title == "Saturday"
        assert _outline_titles(child.children) == ["Afternoon Abseil"]

    def test_outline_entry_targets_entry_page(self) -> None:
        """An entry's bookmark jumps to the page that contains the entry."""
        from pypdf import PdfReader

        entry = _make_entry(42, title="Solo Ridge Traverse", types=["BUSHWALKING"])
        data = LogbookExportData(
            entries=[entry],
            yearly_summaries=[_make_summary(2024)],
            participant_index=[],
        )
        result = self._renderer().render(data)

        outline = _outline_tree(result)
        entry_node = outline[1]
        assert entry_node.title == "Solo Ridge Traverse"
        assert entry_node.page is not None

        reader = PdfReader(io.BytesIO(result))
        assert "Solo Ridge Traverse" in reader.pages[entry_node.page].extract_text()

    def test_outline_absent_for_empty_logbook(self) -> None:
        """An empty logbook renders no document outline."""
        data = LogbookExportData(entries=[], yearly_summaries=[], participant_index=[])
        result = self._renderer().render(data)
        assert _outline_tree(result) == []

    # ── Linked indexes (spec 3.3) ──────────────────────────────

    def test_participant_index_lists_linked_journals(self) -> None:
        """Each contact's row lists the journals they appear in (spec 3.3).

        The entry titles also appear in the entry bodies above, so the listing
        is checked against the index section only — everything from the last
        occurrence of the heading (the first is its contents row) onwards.
        """
        data = _make_indexed_export_data()
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)

        assert "Participant Index" in text
        index_section = text[text.rindex("Participant Index") :]
        assert "Alice Smith" in index_section
        for journal in data.participant_index[0].journals:
            assert journal.title in index_section

    def test_participant_index_links_target_their_entries(self) -> None:
        """Every participant journal name links to that journal's own anchor.

        Compares each link's destination against the destination the contents
        row for that entry resolves to, so a link pointing at the wrong entry —
        or no link at all — fails. Page identity alone would not: every entry
        in this fixture renders on the same page.
        """
        data = _make_indexed_export_data()
        result = self._renderer().render(data)

        destinations = _internal_link_destinations(result)
        by_entry, toc_rows = _entry_destinations(result, data)
        journals = data.participant_index[0].journals

        participant_links = destinations[toc_rows : toc_rows + len(journals)]
        assert participant_links == [by_entry[j.journal_id] for j in journals]
        # Three distinct entries, so three distinct destinations.
        assert len(set(participant_links)) == len(journals)

    def test_activity_type_index_present_and_linked(self) -> None:
        """The activity-type index lists each type's journals as links (spec 3.3)."""
        data = _make_indexed_export_data()
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)

        assert "Activity Type Index" in text
        index_section = text[text.rindex("Activity Type Index") :]
        for label in ("Bushwalking", "Canyoning", "Caving"):
            assert label in index_section

        destinations = _internal_link_destinations(result)
        by_entry, toc_rows = _entry_destinations(result, data)
        expected = [
            by_entry[journal.journal_id]
            for section in data.activity_type_index
            for journal in section.journals
        ]

        # Contents rows, then the participant links, then this section's.
        first_link = toc_rows + len(data.participant_index[0].journals)
        assert destinations[first_link:] == expected

    def test_activity_type_index_lists_journal_under_every_type(self) -> None:
        """A journal is listed under each type row it carries.

        Subtype rows are stored verbatim, so a canyoning journal also carries
        the bushwalking/abseiling/outdoor-activity rows its type depends on and
        appears under all of them (product decision, 2026-07-22).
        """
        types = ["CANYONING", "BUSHWALKING", "ABSEILING_TRIP", "OUTDOOR_ACTIVITY"]
        entry = _make_entry(1, title="Claustral Canyon", types=types)
        reference = LogbookIndexJournal(journal_id=1, title="Claustral Canyon")
        data = LogbookExportData(
            entries=[entry],
            yearly_summaries=[],
            participant_index=[],
            activity_type_index=[
                ActivityTypeIndexEntry(activity_type=t, journals=[reference])
                for t in sorted(types)
            ],
        )

        result = self._renderer().render(data)
        text = _extract_pdf_text(result)

        index_section = text[text.rindex("Activity Type Index") :]
        for label in ("Abseiling Trip", "Bushwalking", "Canyoning", "Outdoor Activity"):
            assert label in index_section

        # One link per section, each targeting the single entry's anchor.
        destinations = _internal_link_destinations(result)
        by_entry, toc_rows = _entry_destinations(result, data)
        assert destinations[toc_rows:] == [by_entry[1]] * len(types)

    def test_activity_type_index_absent_when_empty(self) -> None:
        """No activity-type index section is rendered without index data."""
        data = LogbookExportData(entries=[], yearly_summaries=[], participant_index=[])
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)
        assert "Activity Type Index" not in text

    def test_indexes_listed_in_toc_and_outline(self) -> None:
        """Both index sections appear on the contents page and in the outline."""
        data = _make_indexed_export_data()
        result = self._renderer().render(data)
        text = _extract_pdf_text(result)

        assert "Contents" in text
        assert text.index("Contents") < text.index("Participant Index")

        outline = _outline_tree(result)
        assert _outline_titles(outline) == [
            *[entry.title for entry in data.entries],
            "Participant Index",
            "Activity Type Index",
        ]
        assert all(node.page is not None for node in outline)

    def test_participant_index_renders_long_journal_list(self) -> None:
        """A contact linked to hundreds of journals still renders.

        A linked list that tall exceeds a page, and a table row cannot break
        across pages by default — this pins the row-splitting that keeps a
        prolific participant from failing the whole export.
        """
        entries = [
            _make_entry(i, title=f"Trip Number {i}", day=(i % 28) + 1)
            for i in range(1, 301)
        ]
        references = [
            LogbookIndexJournal(journal_id=entry.id, title=entry.title)
            for entry in entries
        ]
        data = LogbookExportData(
            entries=entries,
            yearly_summaries=[],
            participant_index=[
                ParticipantIndexEntry(
                    contact_id=1,
                    name="Alice Smith",
                    appearances=len(references),
                    journals=references,
                )
            ],
            activity_type_index=[
                ActivityTypeIndexEntry(activity_type="BUSHWALKING", journals=references)
            ],
        )

        result = self._renderer().render(data)

        assert result[:5] == b"%PDF-"
        assert "Trip Number 300" in _extract_pdf_text(result)

    # ── Per-type icon glyphs (spec 3.4) ────────────────────────

    def test_entry_type_labels_carry_their_glyph(self) -> None:
        """Each of an entry's type labels is preceded by that type's glyph."""
        entry = _make_entry(
            1, title="Claustral Canyon", types=["CANYONING", "BUSHWALKING"]
        )
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )

        text = _extract_pdf_text(self._renderer().render(data))

        assert f"{JOURNAL_TYPE_GLYPHS[JournalType.CANYONING]} Canyoning" in text
        assert f"{JOURNAL_TYPE_GLYPHS[JournalType.BUSHWALKING]} Bushwalking" in text

    def test_activity_type_index_rows_carry_their_glyph(self) -> None:
        """The activity-type index labels each section with its glyph."""
        data = _make_indexed_export_data()

        full_text = _extract_pdf_text(self._renderer().render(data))
        # The heading also appears as a contents row, so scope the assertions
        # to the index section itself rather than the entry type labels above.
        text = full_text[full_text.rindex("Activity Type Index") :]

        for journal_type, label in (
            (JournalType.BUSHWALKING, "Bushwalking"),
            (JournalType.CANYONING, "Canyoning"),
            (JournalType.CAVING, "Caving"),
        ):
            assert f"{JOURNAL_TYPE_GLYPHS[journal_type]} {label}" in text

    def test_all_mapped_glyphs_are_covered_by_the_glyph_font(self) -> None:
        """Every mapped glyph has a real outline in the registered font.

        An uncovered codepoint renders as an empty box rather than failing, so
        without this the PDF would silently degrade. A missing system font
        fails here loudly instead of being skipped.
        """
        from reportlab.pdfbase import pdfmetrics

        font_path = resolve_glyph_font_path()
        assert font_path is not None, (
            "No glyph font found — install fonts-dejavu-core (Debian/Ubuntu) "
            "or the distribution equivalent."
        )

        # Rendering a *typed* entry is what registers the font — an empty
        # logbook renders no type label and so would leave it unregistered.
        self._renderer().render(
            LogbookExportData(
                entries=[_make_entry(1, types=["CANYONING"])],
                yearly_summaries=[],
                participant_index=[],
            )
        )
        char_to_glyph = pdfmetrics.getFont(glyph_font_name(font_path)).face.charToGlyph

        uncovered = [
            f"{journal_type}={glyph}"
            for journal_type, glyph in JOURNAL_TYPE_GLYPHS.items()
            if ord(glyph) not in char_to_glyph
        ]
        assert uncovered == []

    def test_glyph_font_name_is_stable_and_collision_free(self) -> None:
        """Distinct paths get distinct names; the same path is always stable.

        The name keys ReportLab's global font registry, so a collision would
        let one path's font be reused for another. The mapping is drawn from a
        path-keyed registry, so this holds by construction rather than by a
        low-probability hash.
        """
        name_a = glyph_font_name("/fonts/a.ttf")
        name_b = glyph_font_name("/fonts/b.ttf")

        assert name_a != name_b
        assert glyph_font_name("/fonts/a.ttf") == name_a
        assert glyph_font_name("/fonts/b.ttf") == name_b

    def test_unusable_glyph_font_degrades_instead_of_failing(self, tmp_path) -> None:
        """A font file that exists but cannot be parsed drops the glyphs.

        Icons are decoration, so a corrupt or unreadable font must never fail
        an export — the same degraded output as having no font at all.
        """
        broken_font = tmp_path / "broken.ttf"
        broken_font.write_bytes(b"not a font")
        entry = _make_entry(1, title="Claustral Canyon", types=["CANYONING"])
        data = LogbookExportData(
            entries=[entry], yearly_summaries=[], participant_index=[]
        )

        result = LogbookPdfRenderer(glyph_font_path=str(broken_font)).render(data)

        text = _extract_pdf_text(result)
        assert result[:5] == b"%PDF-"
        assert "Canyoning" in text
        assert JOURNAL_TYPE_GLYPHS[JournalType.CANYONING] not in text

    def test_labels_render_without_glyphs_when_font_unavailable(self) -> None:
        """With no glyph font the export still succeeds, labels intact."""
        entry = _make_entry(1, title="Claustral Canyon", types=["CANYONING"])
        entry.album_shared_links = ["https://immich.example.com/share/abc123"]
        data = LogbookExportData(
            entries=[entry],
            yearly_summaries=[],
            participant_index=[],
            activity_type_index=[
                ActivityTypeIndexEntry(
                    activity_type="CANYONING",
                    journals=[LogbookIndexJournal(journal_id=1, title=entry.title)],
                )
            ],
        )

        result = LogbookPdfRenderer(glyph_font_path=None).render(data)

        text = _extract_pdf_text(result)
        assert result[:5] == b"%PDF-"
        assert "Canyoning" in text
        assert "Photo Album:" in text
        for glyph in JOURNAL_TYPE_GLYPHS.values():
            assert glyph not in text
