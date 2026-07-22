"""Integration tests for SqlLogbookExportRepository."""

from datetime import UTC, datetime

import pytest
from core_shared.models.journals import (
    ActivityTemplate,
    EventDateRange,
    Journal,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.activity_template_repository import (
    SqlActivityTemplateRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.logbook_export_repository import (
    SqlLogbookExportRepository,
)
from app.core.journal.models.repositories import (
    JournalRepository,
)


@pytest.fixture
def repo(async_connection: AsyncConnection) -> SqlLogbookExportRepository:
    """Provide a logbook export repository."""
    return SqlLogbookExportRepository(async_connection)


@pytest.fixture
def journal_repo(async_connection: AsyncConnection) -> SqlJournalRepository:
    """Provide a journal repository."""
    from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository

    return SqlJournalRepository(async_connection)


@pytest.fixture
def template_repo(
    async_connection: AsyncConnection,
) -> SqlActivityTemplateRepository:
    """Provide an activity template repository."""
    return SqlActivityTemplateRepository(async_connection)


@pytest.mark.asyncio
async def test_get_logbook_entries_empty(repo: SqlLogbookExportRepository) -> None:
    """Test getting logbook entries when none exist."""
    entries = await repo.get_logbook_entries(user_id="user_test_empty")
    assert len(entries) == 0


@pytest.mark.asyncio
async def test_get_logbook_entries_filters(
    repo: SqlLogbookExportRepository,
    journal_repo: JournalRepository,
    async_connection: AsyncConnection,
) -> None:
    """Test that logbook export correctly fetches journals by logbook type."""
    # Create some journals
    user_id = "user_logbook_test"
    now = datetime.now(UTC)

    # Matching journal (BUSHWALKING)
    journal1 = Journal(
        user_id=user_id,
        title="Matching",
        content="Testing",
        event_date_range=EventDateRange(start=now, end=now),
    )
    journal1 = await journal_repo.save(journal1)

    # We must insert directly into journal_types because our tests usually do that via service
    # We'll just insert raw SQL for journal_types
    await async_connection.execute(
        text("INSERT INTO journal_bushwalking_data (journal_id) VALUES (:id)"),
        {"id": journal1.id},
    )

    # Non-matching journal (JOGGING)
    journal2 = Journal(
        user_id=user_id,
        title="Not matching",
        content="Testing",
        event_date_range=EventDateRange(start=now, end=now),
    )
    journal2 = await journal_repo.save(journal2)
    await async_connection.execute(
        text("INSERT INTO journal_jogging_data (journal_id) VALUES (:id)"),
        {"id": journal2.id},
    )

    # Test fetch
    entries = await repo.get_logbook_entries(user_id=user_id)

    assert len(entries) == 1
    assert entries[0].id == journal1.id
    assert entries[0].title == "Matching"
    assert "BUSHWALKING" in entries[0].journal_types


@pytest.mark.asyncio
async def test_get_logbook_entries_hierarchy(
    repo: SqlLogbookExportRepository,
    journal_repo: JournalRepository,
    async_connection: AsyncConnection,
) -> None:
    """Test that logbook export correctly fetches ancestors and descendants."""
    user_id = "user_logbook_hierarchy"
    now = datetime.now(UTC)

    # Parent (not matching type itself)
    parent = Journal(
        user_id=user_id,
        title="Parent Trip",
        content="",
        event_date_range=EventDateRange(start=now, end=now),
    )
    parent = await journal_repo.save(parent)
    await async_connection.execute(
        text("INSERT INTO journal_travel_data (journal_id) VALUES (:id)"),
        {"id": parent.id},
    )

    # Matching child
    child1 = Journal(
        user_id=user_id,
        title="Matching Child",
        content="",
        event_date_range=EventDateRange(start=now, end=now),
        parent_id=parent.id,
    )
    child1 = await journal_repo.save(child1)
    await async_connection.execute(
        text("INSERT INTO journal_canyoning_data (journal_id) VALUES (:id)"),
        {"id": child1.id},
    )

    # Descendant of matching child
    grandchild = Journal(
        user_id=user_id,
        title="Grandchild",
        content="",
        event_date_range=EventDateRange(start=now, end=now),
        parent_id=child1.id,
    )
    grandchild = await journal_repo.save(grandchild)
    # Note doesn't need an explicit insert

    # Unrelated sibling
    sibling = Journal(
        user_id=user_id,
        title="Unrelated sibling",
        content="",
        event_date_range=EventDateRange(start=now, end=now),
        parent_id=parent.id,
    )
    sibling = await journal_repo.save(sibling)
    # Note doesn't need an explicit insert

    # Test fetch
    entries = await repo.get_logbook_entries(user_id=user_id)

    # Should get Parent, Child1, Grandchild, AND Sibling. Sibling is included because the query fetches all descendants of all matching ancestors to preserve the full structural context of the event hierarchy.
    entry_ids = {e.id for e in entries}

    assert parent.id in entry_ids
    assert child1.id in entry_ids
    assert grandchild.id in entry_ids

    # Sibling doesn't have a matching type, and isn't a direct descendant or ancestor of child1.
    # However, because we fetch ALL descendants of ALL ancestors to preserve full hierarchy,
    # and the parent is an ancestor of child1, the sibling (being a descendant of the parent)
    # MUST be included in the final results to maintain the complete structural context.
    assert sibling.id in entry_ids


@pytest.mark.asyncio
async def test_get_logbook_entries_date_and_type_filters(
    repo: SqlLogbookExportRepository,
    journal_repo: JournalRepository,
    async_connection: AsyncConnection,
) -> None:
    """Test that logbook export correctly filters by date range and activity types."""
    user_id = "user_logbook_date_type_filters"

    dt2 = datetime.fromisoformat("2024-01-15T10:00:00Z")
    dt3 = datetime.fromisoformat("2024-02-01T10:00:00Z")

    # Matching type, matching date
    journal1 = Journal(
        user_id=user_id,
        title="Valid Match",
        content="",
        event_date_range=EventDateRange(start=dt2, end=dt2),
    )
    journal1 = await journal_repo.save(journal1)
    await async_connection.execute(
        text("INSERT INTO journal_bushwalking_data (journal_id) VALUES (:id)"),
        {"id": journal1.id},
    )

    # Matching type, outside date
    journal2 = Journal(
        user_id=user_id,
        title="Outside Date",
        content="",
        event_date_range=EventDateRange(start=dt3, end=dt3),
    )
    journal2 = await journal_repo.save(journal2)
    await async_connection.execute(
        text("INSERT INTO journal_bushwalking_data (journal_id) VALUES (:id)"),
        {"id": journal2.id},
    )

    # Non-matching type, matching date
    journal3 = Journal(
        user_id=user_id,
        title="Wrong Type",
        content="",
        event_date_range=EventDateRange(start=dt2, end=dt2),
    )
    journal3 = await journal_repo.save(journal3)
    await async_connection.execute(
        text("INSERT INTO journal_jogging_data (journal_id) VALUES (:id)"),
        {"id": journal3.id},
    )

    # Test fetch with date range that should only catch dt2
    entries = await repo.get_logbook_entries(
        user_id=user_id,
        start_date="2024-01-10T00:00:00Z",
        end_date="2024-01-20T00:00:00Z",
        activity_types=["BUSHWALKING"],
    )

    assert len(entries) == 1
    assert entries[0].id == journal1.id


@pytest.mark.asyncio
async def test_template_name_resolved_from_consolidated_abseiling_template_id(
    repo: SqlLogbookExportRepository,
    journal_repo: JournalRepository,
    template_repo: SqlActivityTemplateRepository,
    async_connection: AsyncConnection,
) -> None:
    """A plain ABSEILING_TRIP resolves its template name from abseiling_data.template_id.

    This is the consolidated single source of truth (ITER16-001): the export must
    read ``journal_abseiling_data.template_id`` rather than the per-subtype columns,
    so plain abseiling trips surface the name and it survives the Phase 5 column drop.
    """
    user_id = "user_abseiling_template_name"
    now = datetime.now(UTC)

    template = await template_repo.save(
        ActivityTemplate(
            name="Empress Falls",
            template_type="abseiling",
            user_id=user_id,
        )
    )

    journal = Journal(
        user_id=user_id,
        title="Abseil From Template",
        content="",
        event_date_range=EventDateRange(start=now, end=now),
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

    entries = await repo.get_logbook_entries(user_id=user_id)

    assert len(entries) == 1
    assert "ABSEILING_TRIP" in entries[0].journal_types
    assert entries[0].template_name == "Empress Falls"


@pytest.mark.asyncio
async def test_template_name_none_when_abseiling_has_no_template(
    repo: SqlLogbookExportRepository,
    journal_repo: JournalRepository,
    async_connection: AsyncConnection,
) -> None:
    """An abseiling journal without a template_id leaves template_name None."""
    user_id = "user_abseiling_no_template"
    now = datetime.now(UTC)

    journal = Journal(
        user_id=user_id,
        title="Abseil Without Template",
        content="",
        event_date_range=EventDateRange(start=now, end=now),
    )
    journal = await journal_repo.save(journal)
    assert journal.id is not None
    await async_connection.execute(
        text("INSERT INTO journal_abseiling_data (journal_id) VALUES (:id)"),
        {"id": journal.id},
    )

    entries = await repo.get_logbook_entries(user_id=user_id)

    assert len(entries) == 1
    assert "ABSEILING_TRIP" in entries[0].journal_types
    assert entries[0].template_name is None


@pytest.mark.asyncio
async def test_template_name_resolved_for_canyoning_from_consolidated_column(
    repo: SqlLogbookExportRepository,
    journal_repo: JournalRepository,
    template_repo: SqlActivityTemplateRepository,
    async_connection: AsyncConnection,
) -> None:
    """A CANYONING journal resolves its template name from the consolidated column.

    CANYONING/CLIMBING/CAVING all depend on ABSEILING_TRIP, so their template
    reference lives on ``journal_abseiling_data.template_id`` (ITER16-001) — this
    proves the export renders the name for a derived type, not just plain
    ABSEILING_TRIP, and no longer relies on the per-subtype ``template_id`` column.
    """
    user_id = "user_canyoning_template_name"
    now = datetime.now(UTC)

    template = await template_repo.save(
        ActivityTemplate(
            name="Claustral Canyon",
            template_type="canyoning",
            user_id=user_id,
        )
    )

    journal = Journal(
        user_id=user_id,
        title="Claustral",
        content="",
        event_date_range=EventDateRange(start=now, end=now),
    )
    journal = await journal_repo.save(journal)
    assert journal.id is not None
    # A canyoning journal carries both its subtype row and the ABSEILING_TRIP row;
    # the template reference is consolidated onto the abseiling row.
    await async_connection.execute(
        text("INSERT INTO journal_canyoning_data (journal_id) VALUES (:id)"),
        {"id": journal.id},
    )
    await async_connection.execute(
        text(
            "INSERT INTO journal_abseiling_data (journal_id, template_id) "
            "VALUES (:id, :template_id)"
        ),
        {"id": journal.id, "template_id": template.id},
    )

    entries = await repo.get_logbook_entries(user_id=user_id)

    assert len(entries) == 1
    assert "CANYONING" in entries[0].journal_types
    assert entries[0].template_name == "Claustral Canyon"


async def _link_immich_album(
    connection: AsyncConnection,
    *,
    journal_id: int,
    album_id: str,
    reference_data: str | None,
) -> None:
    """Link a journal to an Immich album (PHOTO_ALBUM) with reference_data.

    Mirrors the canonical ``sync_metadata`` album link written by the Immich album
    outbox processor (the sole link store since ITER15-001), with ``reference_data``
    carried on that row, so the logbook export sees a real PHOTO_ALBUM link.
    """
    await connection.execute(
        text("""
            INSERT INTO sync_metadata (
                internal_id, integration_source, external_id,
                last_synced_at, version_hash, sync_status,
                internal_entity_type, external_entity_type, reference_data
            ) VALUES (
                :internal_id, 'immich_album', :external_id, now(), 'h', 'success',
                'journal', 'album', :reference_data
            )
        """),
        {
            "internal_id": journal_id,
            "external_id": album_id,
            "reference_data": reference_data,
        },
    )


@pytest.mark.asyncio
async def test_get_logbook_entries_includes_album_shared_link(
    repo: SqlLogbookExportRepository,
    journal_repo: JournalRepository,
    async_connection: AsyncConnection,
) -> None:
    """A PHOTO_ALBUM journal's shared link is surfaced on the logbook entry."""
    user_id = "user_album_shared_link"
    now = datetime.now(UTC)

    journal = Journal(
        user_id=user_id,
        title="Bushwalk With Album",
        content="A great day on the trails",
        event_date_range=EventDateRange(start=now, end=now),
    )
    journal = await journal_repo.save(journal)
    assert journal.id is not None

    # Must also be a logbook type to appear in the export.
    await async_connection.execute(
        text("INSERT INTO journal_bushwalking_data (journal_id) VALUES (:id)"),
        {"id": journal.id},
    )
    await _link_immich_album(
        async_connection,
        journal_id=journal.id,
        album_id="album-1",
        reference_data='{"shared_link_url": "https://immich.example.com/share/xyz"}',
    )

    entries = await repo.get_logbook_entries(user_id=user_id)

    assert len(entries) == 1
    assert "PHOTO_ALBUM" in entries[0].journal_types
    assert entries[0].album_shared_links == ["https://immich.example.com/share/xyz"]


@pytest.mark.asyncio
async def test_get_logbook_entries_includes_every_album_shared_link(
    repo: SqlLogbookExportRepository,
    journal_repo: JournalRepository,
    async_connection: AsyncConnection,
) -> None:
    """A journal linked to several albums surfaces every shared link, in order."""
    user_id = "user_album_shared_links_many"
    now = datetime.now(UTC)

    journal = Journal(
        user_id=user_id,
        title="Bushwalk With Two Albums",
        content="Photos from both cameras",
        event_date_range=EventDateRange(start=now, end=now),
    )
    journal = await journal_repo.save(journal)
    assert journal.id is not None

    await async_connection.execute(
        text("INSERT INTO journal_bushwalking_data (journal_id) VALUES (:id)"),
        {"id": journal.id},
    )
    await _link_immich_album(
        async_connection,
        journal_id=journal.id,
        album_id="album-first",
        reference_data='{"shared_link_url": "https://immich.example.com/share/first"}',
    )
    await _link_immich_album(
        async_connection,
        journal_id=journal.id,
        album_id="album-second",
        reference_data='{"shared_link_url": "https://immich.example.com/share/second"}',
    )

    entries = await repo.get_logbook_entries(user_id=user_id)

    assert len(entries) == 1
    assert entries[0].album_shared_links == [
        "https://immich.example.com/share/first",
        "https://immich.example.com/share/second",
    ]


@pytest.mark.asyncio
async def test_get_logbook_entries_album_without_shared_link(
    repo: SqlLogbookExportRepository,
    journal_repo: JournalRepository,
    async_connection: AsyncConnection,
) -> None:
    """A PHOTO_ALBUM journal with no shared link leaves album_shared_links empty."""
    user_id = "user_album_no_link"
    now = datetime.now(UTC)

    journal = Journal(
        user_id=user_id,
        title="Bushwalk Album No Share",
        content="",
        event_date_range=EventDateRange(start=now, end=now),
    )
    journal = await journal_repo.save(journal)
    assert journal.id is not None

    await async_connection.execute(
        text("INSERT INTO journal_bushwalking_data (journal_id) VALUES (:id)"),
        {"id": journal.id},
    )
    await _link_immich_album(
        async_connection,
        journal_id=journal.id,
        album_id="album-2",
        reference_data='{"album_name": "Summer Trip", "asset_count": 9}',
    )

    entries = await repo.get_logbook_entries(user_id=user_id)

    assert len(entries) == 1
    assert "PHOTO_ALBUM" in entries[0].journal_types
    assert entries[0].album_shared_links == []
