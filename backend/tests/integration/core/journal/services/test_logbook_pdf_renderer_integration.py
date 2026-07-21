"""Integration tests for LogbookPdfRenderer.

Tests end-to-end PDF generation from seeded database data through
the full pipeline: repository -> data service -> PDF renderer.
"""

import io
from datetime import UTC, datetime

import pytest
from core_shared.models.journals import (
    EventDateRange,
    Journal,
    LogbookSummaryCalculator,
    ParticipantIndexCalculator,
)
from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.logbook_export_repository import (
    SqlLogbookExportRepository,
)
from app.core.journal.services.logbook_data_service import LogbookDataService
from app.core.journal.services.logbook_pdf_renderer import LogbookPdfRenderer

# --- Fixtures ---


@pytest.fixture
def renderer() -> LogbookPdfRenderer:
    """Provide a LogbookPdfRenderer instance."""
    return LogbookPdfRenderer()


@pytest.fixture
def export_repo(async_connection: AsyncConnection) -> SqlLogbookExportRepository:
    """Provide a logbook export repository."""
    return SqlLogbookExportRepository(async_connection)


@pytest.fixture
def journal_repo(async_connection: AsyncConnection) -> SqlJournalRepository:
    """Provide a journal repository."""
    return SqlJournalRepository(async_connection)


@pytest.fixture
def data_service(
    export_repo: SqlLogbookExportRepository,
) -> LogbookDataService:
    """Provide a LogbookDataService instance."""
    return LogbookDataService(
        repository=export_repo,
        summary_calculator=LogbookSummaryCalculator(),
        participant_calculator=ParticipantIndexCalculator(),
    )


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pypdf."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts: list[str] = []
    for page in reader.pages:
        text_content = page.extract_text()
        if text_content:
            parts.append(text_content)
    return "\n".join(parts)


def _outline_tree(pdf_bytes: bytes) -> list[tuple[str, list[str]]]:
    """Read the PDF outline as ``(title, [child titles])`` pairs.

    ``pypdf`` returns the document outline as a flat list in which a nested
    list of bookmarks follows the entry it belongs to.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    nodes: list[tuple[str, list[str]]] = []
    for item in reader.outline:
        if isinstance(item, list):
            assert nodes, "nested outline entries without a parent entry"
            title, _ = nodes[-1]
            nodes[-1] = (
                title,
                [str(child.title) for child in item if not isinstance(child, list)],
            )
        else:
            nodes.append((str(item.title), []))
    return nodes


# --- Tests ---


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pdf_generation_from_seeded_data(
    journal_repo: SqlJournalRepository,
    async_connection: AsyncConnection,
    data_service: LogbookDataService,
    renderer: LogbookPdfRenderer,
) -> None:
    """Create journals in real DB and verify full pipeline produces valid PDF."""
    user_id = "user_pdf_test_seeded"

    # Create a bushwalking journal with outdoor activity data
    journal1 = Journal(
        user_id=user_id,
        title="Blue Mountains Bushwalk",
        content="Great day on the trails",
        event_date_range=EventDateRange(
            start=datetime(2024, 3, 15, tzinfo=UTC),
            end=datetime(2024, 3, 15, tzinfo=UTC),
        ),
    )
    journal1 = await journal_repo.save(journal1)
    await async_connection.execute(
        text("INSERT INTO journal_bushwalking_data (journal_id) VALUES (:id)"),
        {"id": journal1.id},
    )
    await async_connection.execute(
        text(
            "INSERT INTO journal_fitness_data (journal_id, distance, elevation_gain) "
            "VALUES (:id, 8500, 350)"
        ),
        {"id": journal1.id},
    )
    await async_connection.execute(
        text(
            "INSERT INTO journal_outdoor_activity_data "
            "(journal_id, weather_conditions, role, in_leadership_role) "
            "VALUES (:id, 'Clear skies', 'Leader', true)"
        ),
        {"id": journal1.id},
    )

    # Create a canyoning journal with abseil pitches
    journal2 = Journal(
        user_id=user_id,
        title="Claustral Canyon",
        content="Technical canyon with several abseils",
        event_date_range=EventDateRange(
            start=datetime(2024, 4, 10, tzinfo=UTC),
            end=datetime(2024, 4, 10, tzinfo=UTC),
        ),
    )
    journal2 = await journal_repo.save(journal2)
    await async_connection.execute(
        text("INSERT INTO journal_canyoning_data (journal_id) VALUES (:id)"),
        {"id": journal2.id},
    )
    await async_connection.execute(
        text(
            "INSERT INTO journal_abseiling_data "
            "(journal_id, number_of_abseils, total_length) "
            "VALUES (:id, 2, 45)"
        ),
        {"id": journal2.id},
    )
    await async_connection.execute(
        text(
            "INSERT INTO abseil_pitches "
            "(journal_id, pitch_number, height, anchor_type, did_setup, did_rescue) "
            "VALUES (:id, 1, 25, 'chains', true, false)"
        ),
        {"id": journal2.id},
    )
    await async_connection.execute(
        text(
            "INSERT INTO abseil_pitches "
            "(journal_id, pitch_number, height, anchor_type, did_setup, did_rescue) "
            "VALUES (:id, 2, 20, 'double bolt', false, false)"
        ),
        {"id": journal2.id},
    )

    # Run through full pipeline
    export_data = await data_service.get_logbook_data(user_id=user_id)
    pdf_bytes = renderer.render(export_data)

    # Verify valid PDF
    assert pdf_bytes[:5] == b"%PDF-"

    # Verify text content
    text_content = _extract_pdf_text(pdf_bytes)
    assert "Outdoor Logbook" in text_content
    assert "Blue Mountains Bushwalk" in text_content
    assert "Claustral Canyon" in text_content
    assert "25" in text_content  # pitch height
    assert "chains" in text_content  # anchor type


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pdf_generation_with_filters(
    journal_repo: SqlJournalRepository,
    async_connection: AsyncConnection,
    export_repo: SqlLogbookExportRepository,
    data_service: LogbookDataService,
    renderer: LogbookPdfRenderer,
) -> None:
    """Seed multiple types, verify only outdoor types appear in logbook PDF."""
    user_id = "user_pdf_test_filters"

    # Create a bushwalking journal
    bush_journal = Journal(
        user_id=user_id,
        title="Bushwalking Only",
        content="Walk in the park",
        event_date_range=EventDateRange(
            start=datetime(2024, 5, 1, tzinfo=UTC),
            end=datetime(2024, 5, 1, tzinfo=UTC),
        ),
    )
    bush_journal = await journal_repo.save(bush_journal)
    await async_connection.execute(
        text("INSERT INTO journal_bushwalking_data (journal_id) VALUES (:id)"),
        {"id": bush_journal.id},
    )

    # Create a jogging journal (not an outdoor logbook type)
    jog_journal = Journal(
        user_id=user_id,
        title="Morning Jog Should Not Appear",
        content="Quick jog",
        event_date_range=EventDateRange(
            start=datetime(2024, 5, 2, tzinfo=UTC),
            end=datetime(2024, 5, 2, tzinfo=UTC),
        ),
    )
    jog_journal = await journal_repo.save(jog_journal)
    await async_connection.execute(
        text("INSERT INTO journal_jogging_data (journal_id) VALUES (:id)"),
        {"id": jog_journal.id},
    )

    # Generate PDF from full pipeline (logbook export only fetches outdoor types)
    export_data = await data_service.get_logbook_data(user_id=user_id)
    pdf_bytes = renderer.render(export_data)

    text_content = _extract_pdf_text(pdf_bytes)
    assert "Bushwalking Only" in text_content
    # Jogging journals should not be included because the logbook export
    # repository only fetches outdoor activity types
    assert "Morning Jog Should Not Appear" not in text_content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pdf_generation_includes_album_shared_link(
    journal_repo: SqlJournalRepository,
    async_connection: AsyncConnection,
    data_service: LogbookDataService,
    renderer: LogbookPdfRenderer,
) -> None:
    """An Immich-linked PHOTO_ALBUM journal renders its shared link in the PDF."""
    user_id = "user_pdf_album_link"

    journal = Journal(
        user_id=user_id,
        title="Bushwalk With Photos",
        content="A great day on the trails",
        event_date_range=EventDateRange(
            start=datetime(2024, 6, 1, tzinfo=UTC),
            end=datetime(2024, 6, 1, tzinfo=UTC),
        ),
    )
    journal = await journal_repo.save(journal)
    await async_connection.execute(
        text("INSERT INTO journal_bushwalking_data (journal_id) VALUES (:id)"),
        {"id": journal.id},
    )
    # Link the journal to an Immich album with a public shared link.
    await async_connection.execute(
        text("""
            INSERT INTO sync_metadata (
                internal_id, integration_source, external_id,
                last_synced_at, version_hash, sync_status,
                internal_entity_type, external_entity_type, reference_data
            ) VALUES (:id, 'immich_album', 'album-pdf-1', now(), 'h', 'success',
                      'journal', 'album', :ref)
        """),
        {
            "id": journal.id,
            "ref": '{"shared_link_url": "https://immich.example.com/share/xyz"}',
        },
    )

    export_data = await data_service.get_logbook_data(user_id=user_id)
    pdf_bytes = renderer.render(export_data)

    assert pdf_bytes[:5] == b"%PDF-"
    text_content = _extract_pdf_text(pdf_bytes)
    assert "Bushwalk With Photos" in text_content
    assert "Photo Album:" in text_content
    assert "https://immich.example.com/share/xyz" in text_content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pdf_generation_empty_result(
    data_service: LogbookDataService,
    renderer: LogbookPdfRenderer,
) -> None:
    """No matching journals produces a valid empty PDF (cover only)."""
    export_data = await data_service.get_logbook_data(
        user_id="user_pdf_test_nonexistent"
    )

    pdf_bytes = renderer.render(export_data)

    # Should still be a valid PDF
    assert pdf_bytes[:5] == b"%PDF-"
    text_content = _extract_pdf_text(pdf_bytes)
    assert "Outdoor Logbook" in text_content
    assert "0 journal entries" in text_content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pdf_navigation_summary_first_and_toc(
    journal_repo: SqlJournalRepository,
    async_connection: AsyncConnection,
    data_service: LogbookDataService,
    renderer: LogbookPdfRenderer,
) -> None:
    """Full pipeline lays the PDF out summary-first with a table of contents.

    Seeds outdoor journals that yield a yearly summary, then asserts the
    summary section precedes the entries and a linked contents page is present.
    """
    user_id = "user_pdf_test_navigation"

    bushwalk = Journal(
        user_id=user_id,
        title="Grose Valley Bushwalk",
        content="Long day out",
        event_date_range=EventDateRange(
            start=datetime(2024, 6, 1, tzinfo=UTC),
            end=datetime(2024, 6, 1, tzinfo=UTC),
        ),
    )
    bushwalk = await journal_repo.save(bushwalk)
    await async_connection.execute(
        text("INSERT INTO journal_bushwalking_data (journal_id) VALUES (:id)"),
        {"id": bushwalk.id},
    )

    canyon = Journal(
        user_id=user_id,
        title="Empress Canyon",
        content="Classic beginner canyon",
        event_date_range=EventDateRange(
            start=datetime(2024, 7, 12, tzinfo=UTC),
            end=datetime(2024, 7, 12, tzinfo=UTC),
        ),
    )
    canyon = await journal_repo.save(canyon)
    await async_connection.execute(
        text("INSERT INTO journal_canyoning_data (journal_id) VALUES (:id)"),
        {"id": canyon.id},
    )
    await async_connection.execute(
        text(
            "INSERT INTO journal_abseiling_data "
            "(journal_id, number_of_abseils, total_length) "
            "VALUES (:id, 3, 60)"
        ),
        {"id": canyon.id},
    )

    export_data = await data_service.get_logbook_data(user_id=user_id)
    pdf_bytes = renderer.render(export_data)

    assert pdf_bytes[:5] == b"%PDF-"
    text_content = _extract_pdf_text(pdf_bytes)

    # The summary section and a contents page are both present...
    assert "Yearly Summaries" in text_content
    assert "Contents" in text_content
    assert "Grose Valley Bushwalk" in text_content
    # ...and the summary precedes the entry SECTION. The entry title now also
    # appears in the TOC (which follows the summary), so anchor the ordering on
    # the entry body content, which only appears in the section itself.
    assert "Long day out" in text_content
    assert text_content.index("Yearly Summaries") < text_content.index("Long day out")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pdf_document_outline_from_seeded_data(
    journal_repo: SqlJournalRepository,
    async_connection: AsyncConnection,
    data_service: LogbookDataService,
    renderer: LogbookPdfRenderer,
) -> None:
    """The full pipeline produces a document outline mirroring the hierarchy.

    Seeds a parent trip with a child activity, plus a trip in a second year, so
    the repository returns both a nested entry and a two-year summary. Asserts
    the generated PDF carries a viewer-navigable outline in the real ordering:
    summaries newest-first, trips oldest-first, child activities nested.
    """
    user_id = "user_pdf_test_outline"

    trip = Journal(
        user_id=user_id,
        title="Kanangra Weekend",
        content="Two days out",
        event_date_range=EventDateRange(
            start=datetime(2024, 8, 3, tzinfo=UTC),
            end=datetime(2024, 8, 4, tzinfo=UTC),
        ),
    )
    trip = await journal_repo.save(trip)
    await async_connection.execute(
        text("INSERT INTO journal_bushwalking_data (journal_id) VALUES (:id)"),
        {"id": trip.id},
    )

    child = Journal(
        user_id=user_id,
        title="Kalang Falls Abseil",
        content="Three pitches",
        parent_id=trip.id,
        event_date_range=EventDateRange(
            start=datetime(2024, 8, 4, tzinfo=UTC),
            end=datetime(2024, 8, 4, tzinfo=UTC),
        ),
    )
    child = await journal_repo.save(child)
    await async_connection.execute(
        text("INSERT INTO journal_canyoning_data (journal_id) VALUES (:id)"),
        {"id": child.id},
    )
    await async_connection.execute(
        text(
            "INSERT INTO journal_abseiling_data "
            "(journal_id, number_of_abseils, total_length) "
            "VALUES (:id, 3, 75)"
        ),
        {"id": child.id},
    )

    later_trip = Journal(
        user_id=user_id,
        title="Empress Canyon",
        content="Classic beginner canyon",
        event_date_range=EventDateRange(
            start=datetime(2025, 2, 15, tzinfo=UTC),
            end=datetime(2025, 2, 15, tzinfo=UTC),
        ),
    )
    later_trip = await journal_repo.save(later_trip)
    await async_connection.execute(
        text("INSERT INTO journal_canyoning_data (journal_id) VALUES (:id)"),
        {"id": later_trip.id},
    )

    export_data = await data_service.get_logbook_data(user_id=user_id)
    pdf_bytes = renderer.render(export_data)

    assert pdf_bytes[:5] == b"%PDF-"
    outline = _outline_tree(pdf_bytes)

    assert [title for title, _ in outline] == [
        "Summary",
        "Kanangra Weekend",
        "Empress Canyon",
    ]
    assert outline[0][1] == ["Year 2025", "Year 2024"]
    assert outline[1][1] == ["Kalang Falls Abseil"]
    assert outline[2][1] == []
