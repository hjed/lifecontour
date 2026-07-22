"""Integration tests for the logbook export API endpoint.

Tests POST /api/journals/export/outdoor-logbook with real database data,
verifying PDF generation, filtering, and authentication requirements.
"""

import io
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository

# ─── Helpers ─────────────────────────────────────────────────────────


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pypdf."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts: list[str] = []
    for page in reader.pages:
        text_content = page.extract_text()
        if text_content:
            parts.append(text_content)
    return "\n".join(parts)


def _internal_link_destinations(pdf_bytes: bytes) -> list[tuple[int, str, str]]:
    """Resolve every internal link to its exact destination, in document order.

    ReportLab writes ``<a href="#anchor">`` as a ``/Link`` annotation whose
    ``/Dest`` is ``[page, '/XYZ', x, y, zoom]`` — the coordinates of the
    anchored paragraph. External ``/URI`` links carry no ``/Dest`` and are
    ignored. Keeping the coordinates identifies *which* anchor a link points
    at; a page index alone cannot, since a short export puts every entry on
    one page.

    Annotations are read page by page in emission order, so the result follows
    document order: one contents row per navigable section, then each index
    section's links.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_indexes = {
        page.indirect_reference.idnum: idx
        for idx, page in enumerate(reader.pages)
        if page.indirect_reference is not None
    }

    destinations: list[tuple[int, str, str]] = []
    for page in reader.pages:
        for annotation in page.get("/Annots") or []:
            obj = annotation.get_object()
            if obj.get("/Subtype") != "/Link" or "/Dest" not in obj:
                continue
            dest = obj["/Dest"]
            assert isinstance(dest, list) and hasattr(dest[0], "idnum"), dest
            destinations.append(
                (page_indexes[dest[0].idnum], str(dest[2]), str(dest[3]))
            )
    return destinations


def _contents_row_labels(pdf_bytes: bytes) -> list[str]:
    """The contents page's rows, in document order, read from the outline.

    The renderer builds the contents page and the document outline from one
    navigation tree: every top-level section gets a contents row, and the
    summary's years are the only children the contents page expands (child
    activities nest in the outline alone). Deriving the rows from the rendered
    document keeps the link arithmetic tied to what the export actually
    contains, rather than to a count that silently rots when a fixture changes.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))

    labels: list[str] = []
    children: list[str] = []
    for item in reader.outline:
        if isinstance(item, list):
            children = [str(c.title) for c in item if not isinstance(c, list)]
            if labels and labels[-1] == "Summary":
                labels.extend(children)
        else:
            labels.append(str(item.title))
    return labels


def _index_link_destinations(
    pdf_bytes: bytes, entry_titles: list[str]
) -> tuple[list[tuple[int, str, str]], list[tuple[int, str, str]]]:
    """Split the document's link destinations into contents rows and index links.

    Returns the destinations the named entries' contents rows resolve to, and
    the destinations of every link that follows the contents page — i.e. the
    index sections' links, which close the document.
    """
    destinations = _internal_link_destinations(pdf_bytes)
    rows = _contents_row_labels(pdf_bytes)
    assert len(destinations) > len(rows), "no index links were rendered"

    by_row = dict(zip(rows, destinations[: len(rows)], strict=True))
    return [by_row[title] for title in entry_titles], destinations[len(rows) :]


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def unauthenticated_client(test_settings, async_connection: AsyncConnection):
    """Create async test client without authentication."""
    from dishka import Provider, Scope, make_async_container, provide
    from dishka.integrations.fastapi import FastapiProvider, setup_dishka
    from httpx import ASGITransport, AsyncClient

    from app.infrastructure.di.auth import AuthProvider
    from app.infrastructure.di.contacts import ContactProvider
    from app.infrastructure.di.infrastructure import InfrastructureProvider
    from app.infrastructure.di.integrations import IntegrationProvider
    from app.infrastructure.di.journal import JournalProvider
    from app.infrastructure.di.settings import SettingsProvider
    from app.main import create_app

    class TestDatabaseProvider(Provider):
        @provide(scope=Scope.REQUEST)
        def get_connection(self) -> AsyncConnection:
            return async_connection

    app = create_app(settings=test_settings)

    test_container = make_async_container(
        TestDatabaseProvider(),
        InfrastructureProvider(),
        AuthProvider(),
        ContactProvider(),
        JournalProvider(),
        SettingsProvider(),
        IntegrationProvider(),
        FastapiProvider(),
        context={"settings": test_settings},
    )
    setup_dishka(test_container, app)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


@pytest.fixture
def journal_repo(async_connection: AsyncConnection) -> SqlJournalRepository:
    """Provide a journal repository."""
    return SqlJournalRepository(async_connection)


@pytest.fixture
async def seeded_outdoor_journals(
    async_connection: AsyncConnection,
    journal_repo: SqlJournalRepository,
) -> dict[str, int]:
    """Seed outdoor journals for export tests. Returns dict of title -> id."""
    from core_shared.models.journals import EventDateRange, Journal

    ids: dict[str, int] = {}

    # Bushwalking journal in January 2024
    j1 = Journal(
        user_id="test-user-123",
        title="Blue Mountains Bushwalk",
        content="Great day on the trails",
        event_date_range=EventDateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 15, tzinfo=UTC),
        ),
    )
    j1 = await journal_repo.save(j1)
    assert j1.id is not None
    ids["Blue Mountains Bushwalk"] = j1.id
    await async_connection.execute(
        text("INSERT INTO journal_bushwalking_data (journal_id) VALUES (:id)"),
        {"id": j1.id},
    )

    # Canyoning journal in March 2024
    j2 = Journal(
        user_id="test-user-123",
        title="Claustral Canyon",
        content="Technical canyon trip",
        event_date_range=EventDateRange(
            start=datetime(2024, 3, 10, tzinfo=UTC),
            end=datetime(2024, 3, 10, tzinfo=UTC),
        ),
    )
    j2 = await journal_repo.save(j2)
    assert j2.id is not None
    ids["Claustral Canyon"] = j2.id
    await async_connection.execute(
        text("INSERT INTO journal_canyoning_data (journal_id) VALUES (:id)"),
        {"id": j2.id},
    )

    # Caving journal in June 2024
    j3 = Journal(
        user_id="test-user-123",
        title="Jenolan Caves Trip",
        content="Explored the caves",
        event_date_range=EventDateRange(
            start=datetime(2024, 6, 20, tzinfo=UTC),
            end=datetime(2024, 6, 20, tzinfo=UTC),
        ),
    )
    j3 = await journal_repo.save(j3)
    assert j3.id is not None
    ids["Jenolan Caves Trip"] = j3.id
    await async_connection.execute(
        text("INSERT INTO journal_caving_data (journal_id) VALUES (:id)"),
        {"id": j3.id},
    )

    return ids


# ─── Tests ───────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
class TestLogbookExportEndpoint:
    """Tests for POST /api/journals/export/outdoor-logbook."""

    async def test_export_unauthenticated(self, unauthenticated_client) -> None:
        """Unauthenticated requests are rejected with 401."""
        response = await unauthenticated_client.post(
            "/api/journals/export/outdoor-logbook",
            json={},
        )
        assert response.status_code == 401

    async def test_export_returns_valid_pdf(
        self,
        authenticated_client,
        seeded_outdoor_journals,
    ) -> None:
        """Authenticated export returns a valid PDF with seeded journal data."""
        response = await authenticated_client.post(
            "/api/journals/export/outdoor-logbook",
            json={},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "content-disposition" in response.headers
        assert "outdoor_logbook" in response.headers["content-disposition"]

        pdf_bytes = response.content
        assert pdf_bytes[:5] == b"%PDF-"

        text_content = _extract_pdf_text(pdf_bytes)
        assert "Outdoor Logbook" in text_content
        assert "Blue Mountains Bushwalk" in text_content
        assert "Claustral Canyon" in text_content

    async def test_export_with_date_range_filter(
        self,
        authenticated_client,
        seeded_outdoor_journals,
    ) -> None:
        """Export with date range filters only includes journals in range."""
        response = await authenticated_client.post(
            "/api/journals/export/outdoor-logbook",
            json={
                "start_date": "2024-01-01",
                "end_date": "2024-02-28",
            },
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

        text_content = _extract_pdf_text(response.content)
        assert "Blue Mountains Bushwalk" in text_content
        assert "Claustral Canyon" not in text_content
        assert "Jenolan Caves Trip" not in text_content

    async def test_export_with_activity_type_filter(
        self,
        authenticated_client,
        seeded_outdoor_journals,
    ) -> None:
        """Export with activity type filter only includes matching types."""
        response = await authenticated_client.post(
            "/api/journals/export/outdoor-logbook",
            json={
                "activity_types": ["CANYONING"],
            },
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

        text_content = _extract_pdf_text(response.content)
        assert "Claustral Canyon" in text_content
        assert "Blue Mountains Bushwalk" not in text_content

    async def test_export_includes_photo_album_shared_link(
        self,
        authenticated_client,
        async_connection: AsyncConnection,
        journal_repo: SqlJournalRepository,
    ) -> None:
        """Exported PDF includes the Immich album shared link for linked journals."""
        from core_shared.models.journals import EventDateRange, Journal

        journal = Journal(
            user_id="test-user-123",
            title="Bushwalk With Album",
            content="A great day on the trails",
            event_date_range=EventDateRange(
                start=datetime(2024, 2, 5, tzinfo=UTC),
                end=datetime(2024, 2, 5, tzinfo=UTC),
            ),
        )
        journal = await journal_repo.save(journal)
        assert journal.id is not None
        await async_connection.execute(
            text("INSERT INTO journal_bushwalking_data (journal_id) VALUES (:id)"),
            {"id": journal.id},
        )
        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata (
                    internal_id, integration_source, external_id,
                    last_synced_at, version_hash, sync_status,
                    internal_entity_type, external_entity_type, reference_data
                ) VALUES (:id, 'immich_album', 'album-api-1', now(), 'h', 'success',
                          'journal', 'album', :ref)
            """),
            {
                "id": journal.id,
                "ref": '{"shared_link_url": "https://immich.example.com/share/xyz"}',
            },
        )

        response = await authenticated_client.post(
            "/api/journals/export/outdoor-logbook",
            json={},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

        text_content = _extract_pdf_text(response.content)
        assert "Bushwalk With Album" in text_content
        assert "Photo Album:" in text_content
        assert "https://immich.example.com/share/xyz" in text_content

    async def test_export_includes_template_name_for_abseiling_trip(
        self,
        authenticated_client,
        async_connection: AsyncConnection,
        journal_repo: SqlJournalRepository,
    ) -> None:
        """Exported PDF shows 'Based on: <template>' for a plain abseiling trip.

        Proves the export resolves the template name from the consolidated
        ``journal_abseiling_data.template_id`` (ITER16-001 Phase 4).
        """
        from core_shared.models.journals import (
            ActivityTemplate,
            EventDateRange,
            Journal,
        )

        from app.core.journal.adapters.sql.activity_template_repository import (
            SqlActivityTemplateRepository,
        )

        template = await SqlActivityTemplateRepository(async_connection).save(
            ActivityTemplate(
                name="Empress Falls",
                template_type="abseiling",
                user_id="test-user-123",
            )
        )

        journal = Journal(
            user_id="test-user-123",
            title="Abseil From Template",
            content="Multi-pitch abseil",
            event_date_range=EventDateRange(
                start=datetime(2024, 4, 12, tzinfo=UTC),
                end=datetime(2024, 4, 12, tzinfo=UTC),
            ),
        )
        journal = await journal_repo.save(journal)
        assert journal.id is not None
        await async_connection.execute(
            text(
                "INSERT INTO journal_abseiling_data (journal_id, template_id) "
                "VALUES (:id, :template_id)"
            ),
            {"id": journal.id, "template_id": template.id},
        )

        response = await authenticated_client.post(
            "/api/journals/export/outdoor-logbook",
            json={},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

        text_content = _extract_pdf_text(response.content)
        assert "Abseil From Template" in text_content
        assert "Based on:" in text_content
        assert "Empress Falls" in text_content

    async def test_export_omits_template_name_when_absent(
        self,
        authenticated_client,
        async_connection: AsyncConnection,
        journal_repo: SqlJournalRepository,
    ) -> None:
        """Exported PDF omits the 'Based on:' line for an abseiling trip with no template."""
        from core_shared.models.journals import EventDateRange, Journal

        journal = Journal(
            user_id="test-user-123",
            title="Abseil Without Template",
            content="No template linked",
            event_date_range=EventDateRange(
                start=datetime(2024, 5, 3, tzinfo=UTC),
                end=datetime(2024, 5, 3, tzinfo=UTC),
            ),
        )
        journal = await journal_repo.save(journal)
        assert journal.id is not None
        await async_connection.execute(
            text("INSERT INTO journal_abseiling_data (journal_id) VALUES (:id)"),
            {"id": journal.id},
        )

        response = await authenticated_client.post(
            "/api/journals/export/outdoor-logbook",
            json={},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

        text_content = _extract_pdf_text(response.content)
        assert "Abseil Without Template" in text_content
        assert "Based on:" not in text_content

    async def test_export_participant_index_links_to_entries(
        self,
        authenticated_client,
        async_connection: AsyncConnection,
        journal_repo: SqlJournalRepository,
    ) -> None:
        """The participant index lists a qualifying contact's linked journals.

        Seeds one contact at the ``min_appearances = 3`` boundary (exactly
        three entries) and a second contact just below it, then asserts the
        qualifying contact's journals are listed and each name links to the
        page holding that entry.
        """
        from core_shared.models.journals import EventDateRange, Journal

        titles = ["Grose Valley Walk", "Empress Canyon", "Wollangambe Float"]
        journal_ids: list[int] = []
        for index, title in enumerate(titles):
            journal = await journal_repo.save(
                Journal(
                    user_id="test-user-123",
                    title=title,
                    content=f"Trip notes for {title}",
                    event_date_range=EventDateRange(
                        start=datetime(2024, 8, index + 1, tzinfo=UTC),
                        end=datetime(2024, 8, index + 1, tzinfo=UTC),
                    ),
                )
            )
            assert journal.id is not None
            journal_ids.append(journal.id)
            await async_connection.execute(
                text("INSERT INTO journal_bushwalking_data (journal_id) VALUES (:id)"),
                {"id": journal.id},
            )

        frequent_id = (
            await async_connection.execute(
                text("INSERT INTO contacts (first_name) VALUES (:name) RETURNING id"),
                {"name": "Frequentflyer"},
            )
        ).scalar()
        occasional_id = (
            await async_connection.execute(
                text("INSERT INTO contacts (first_name) VALUES (:name) RETURNING id"),
                {"name": "Occasionalguest"},
            )
        ).scalar()

        for journal_id in journal_ids:
            await async_connection.execute(
                text(
                    "INSERT INTO journal_contact_relationships "
                    "(journal_id, contact_id, relationship_type) "
                    "VALUES (:journal_id, :contact_id, 'PARTICIPANT')"
                ),
                {"journal_id": journal_id, "contact_id": frequent_id},
            )
        for journal_id in journal_ids[:2]:
            await async_connection.execute(
                text(
                    "INSERT INTO journal_contact_relationships "
                    "(journal_id, contact_id, relationship_type) "
                    "VALUES (:journal_id, :contact_id, 'INVITEE')"
                ),
                {"journal_id": journal_id, "contact_id": occasional_id},
            )

        response = await authenticated_client.post(
            "/api/journals/export/outdoor-logbook",
            json={"start_date": "2024-08-01", "end_date": "2024-08-31"},
        )
        assert response.status_code == 200

        text_content = _extract_pdf_text(response.content)
        assert "Participant Index" in text_content

        # The indexes are the last sections, so everything from the participant
        # heading onwards is index content — the contact on two entries appears
        # in the entry bodies above it but never in the index itself. The
        # heading is the *last* occurrence; the first is its contents row.
        indexes = text_content[text_content.rindex("Participant Index") :]
        assert "Frequentflyer" in indexes
        assert "Occasionalguest" in text_content
        assert "Occasionalguest" not in indexes

        # Each trip's contents row gives the authoritative destination for that
        # entry's anchor. The index links that follow must resolve to the same
        # places: the contact's three journals, then the single bushwalking
        # section listing the same three.
        entry_destinations, index_links = _index_link_destinations(
            response.content, titles
        )
        assert len(set(entry_destinations)) == len(titles)  # three distinct anchors
        assert index_links == entry_destinations * 2

    async def test_export_activity_type_index_links_to_entries(
        self,
        authenticated_client,
        seeded_outdoor_journals,
    ) -> None:
        """The activity-type index groups the seeded types and links each entry."""
        response = await authenticated_client.post(
            "/api/journals/export/outdoor-logbook",
            json={},
        )
        assert response.status_code == 200

        text_content = _extract_pdf_text(response.content)
        assert "Activity Type Index" in text_content
        index_section = text_content[text_content.rindex("Activity Type Index") :]
        for label in ("Bushwalking", "Canyoning", "Caving"):
            assert label in index_section

        # Each seeded journal carries exactly one type and the sections are
        # type-sorted, so the index links run one per section, each resolving
        # to the destination that entry's own contents row resolves to.
        titles_by_type = {
            "BUSHWALKING": "Blue Mountains Bushwalk",
            "CANYONING": "Claustral Canyon",
            "CAVING": "Jenolan Caves Trip",
        }
        assert set(titles_by_type.values()) == set(seeded_outdoor_journals)

        entry_destinations, index_links = _index_link_destinations(
            response.content, [titles_by_type[t] for t in sorted(titles_by_type)]
        )
        assert len(set(entry_destinations)) == len(titles_by_type)
        assert index_links == entry_destinations

    async def test_export_empty_result(
        self,
        authenticated_client,
    ) -> None:
        """Export with no matching journals returns a valid PDF with cover page."""
        response = await authenticated_client.post(
            "/api/journals/export/outdoor-logbook",
            json={
                "start_date": "2099-01-01",
                "end_date": "2099-12-31",
            },
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

        pdf_bytes = response.content
        assert pdf_bytes[:5] == b"%PDF-"

        text_content = _extract_pdf_text(pdf_bytes)
        assert "Outdoor Logbook" in text_content
        assert "0 journal entries" in text_content
