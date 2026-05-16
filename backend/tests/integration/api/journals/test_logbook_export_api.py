"""Integration tests for the logbook export API endpoint.

Tests POST /api/journals/export/outdoor-logbook with real database data,
verifying PDF generation, filtering, and authentication requirements.
"""

import io
from datetime import UTC, datetime

import pytest
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


# ─── Fixtures ────────────────────────────────────────────────────────


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
