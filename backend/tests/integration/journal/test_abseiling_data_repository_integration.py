"""Integration tests for SqlAbseilingDataRepository."""

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import (
    AbseilingData,
    ActivityTemplate,
    EventDateRange,
    Journal,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.abseiling_data_repository import (
    SqlAbseilingDataRepository,
)
from app.core.journal.adapters.sql.activity_template_repository import (
    SqlActivityTemplateRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository


@pytest_asyncio.fixture
async def abseiling_repository(
    async_connection: AsyncConnection,
) -> SqlAbseilingDataRepository:
    """Create an abseiling data repository for testing."""
    return SqlAbseilingDataRepository(async_connection)


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    """Create a journal repository for testing."""
    return SqlJournalRepository(async_connection)


@pytest_asyncio.fixture
async def template_repository(
    async_connection: AsyncConnection,
) -> SqlActivityTemplateRepository:
    """Create a template repository for testing."""
    return SqlActivityTemplateRepository(async_connection)


@pytest_asyncio.fixture
async def test_template(
    template_repository: SqlActivityTemplateRepository,
) -> ActivityTemplate:
    """Create a test abseiling template."""
    template = ActivityTemplate(
        name="Empress Falls",
        template_type="abseiling",
        user_id="test-user-123",
    )
    return await template_repository.save(template)


@pytest_asyncio.fixture
async def test_journal(
    journal_repository: SqlJournalRepository,
) -> Journal:
    """Create a test journal."""
    now = datetime.now(UTC)
    journal = Journal(
        user_id="test-user-123",
        title="Abseiling Trip - Blue Mountains",
        content="Multi-pitch abseil in the Blue Mountains",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=6),
        ),
    )
    return await journal_repository.save(journal)


@pytest.mark.integration
class TestAbseilingDataRepositorySave:
    """Test abseiling data save operations."""

    async def test_save_creates_new_abseiling_data(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test creating abseiling data (adding ABSEILING_TRIP type to journal)."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_abseils=5,
            total_length=120,
        )

        saved = await abseiling_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.number_of_abseils == 5
        assert saved.total_length == 120
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_minimal_data(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test creating abseiling data with only required fields."""
        data = AbseilingData(journal_id=test_journal.id)  # type: ignore[arg-type]

        saved = await abseiling_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.number_of_abseils is None
        assert saved.total_length is None
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_updates_existing_data(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test updating existing abseiling data."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_abseils=3,
            total_length=80,
        )
        await abseiling_repository.save(data)

        updated_data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_abseils=7,
            total_length=200,
        )
        saved = await abseiling_repository.save(updated_data)

        assert saved.number_of_abseils == 7
        assert saved.total_length == 200


@pytest.mark.integration
class TestAbseilingDataRepositoryFind:
    """Test abseiling data find operations."""

    async def test_find_by_journal_id_returns_data(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test finding abseiling data by journal ID."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_abseils=5,
            total_length=120,
        )
        await abseiling_repository.save(data)

        found = await abseiling_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.journal_id == test_journal.id
        assert found.number_of_abseils == 5
        assert found.total_length == 120

    async def test_find_by_journal_id_returns_none_when_not_found(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
    ):
        """Test finding abseiling data returns None when not found."""
        found = await abseiling_repository.find_by_journal_id(99999)

        assert found is None

    async def test_find_preserves_zero_values(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test that zero values are correctly persisted and retrieved."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_abseils=0,
            total_length=0,
        )
        await abseiling_repository.save(data)

        found = await abseiling_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.number_of_abseils == 0
        assert found.total_length == 0


@pytest.mark.integration
class TestAbseilingDataRepositoryDelete:
    """Test abseiling data delete operations."""

    async def test_delete_removes_data(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test deleting abseiling data."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_abseils=3,
        )
        await abseiling_repository.save(data)

        await abseiling_repository.delete(test_journal.id)  # type: ignore[arg-type]

        found = await abseiling_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found is None

    async def test_delete_nonexistent_data_does_not_error(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
    ):
        """Test deleting non-existent data does not raise error."""
        await abseiling_repository.delete(99999)


@pytest.mark.integration
class TestAbseilingDataRepositoryAggregateFields:
    """Test abseiling data aggregate fields (number_of_setups, number_of_rescues)."""

    async def test_save_with_aggregate_fields(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test creating abseiling data with new aggregate fields."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_abseils=5,
            total_length=120,
            number_of_setups=3,
            number_of_rescues=1,
        )

        saved = await abseiling_repository.save(data)

        assert saved.number_of_setups == 3
        assert saved.number_of_rescues == 1

    async def test_find_preserves_aggregate_fields(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test that aggregate fields are correctly persisted and retrieved."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_setups=2,
            number_of_rescues=0,
        )
        await abseiling_repository.save(data)

        found = await abseiling_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.number_of_setups == 2
        assert found.number_of_rescues == 0

    async def test_update_aggregate_fields(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test updating aggregate fields via upsert."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_setups=1,
            number_of_rescues=0,
        )
        await abseiling_repository.save(data)

        updated = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_setups=4,
            number_of_rescues=2,
        )
        saved = await abseiling_repository.save(updated)

        assert saved.number_of_setups == 4
        assert saved.number_of_rescues == 2

    async def test_null_aggregate_fields(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test that aggregate fields default to None when not provided."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
        )
        saved = await abseiling_repository.save(data)

        assert saved.number_of_setups is None
        assert saved.number_of_rescues is None


@pytest.mark.integration
class TestAbseilingDataRepositoryTemplateId:
    """Test abseiling data consolidated template_id persistence (ITER16-001)."""

    async def test_save_persists_template_id(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
        test_template: ActivityTemplate,
    ):
        """Test that template_id is persisted on save."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_abseils=4,
            template_id=test_template.id,
        )

        saved = await abseiling_repository.save(data)

        assert str(saved.template_id) == str(test_template.id)

    async def test_find_returns_template_id(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
        test_template: ActivityTemplate,
    ):
        """Test that template_id is returned when reading back."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            template_id=test_template.id,
        )
        await abseiling_repository.save(data)

        found = await abseiling_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert str(found.template_id) == str(test_template.id)

    async def test_save_without_template_id_keeps_none(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test that omitting template_id persists NULL (regression)."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_abseils=2,
        )
        await abseiling_repository.save(data)

        found = await abseiling_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.template_id is None

    async def test_update_preserves_template_id_via_upsert(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
        test_template: ActivityTemplate,
    ):
        """Test that re-saving with template_id keeps it on the upsert."""
        await abseiling_repository.save(
            AbseilingData(
                journal_id=test_journal.id,  # type: ignore[arg-type]
                template_id=test_template.id,
            )
        )

        saved = await abseiling_repository.save(
            AbseilingData(
                journal_id=test_journal.id,  # type: ignore[arg-type]
                number_of_abseils=6,
                template_id=test_template.id,
            )
        )

        assert saved.number_of_abseils == 6
        assert str(saved.template_id) == str(test_template.id)

    async def test_field_only_edit_preserves_template_id(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
        test_template: ActivityTemplate,
    ):
        """A read-modify-write edit of another field must not clear template_id.

        Mirrors how the service helpers update type data: load the existing row
        (which now carries template_id), `dataclasses.replace` a subset of
        fields, and save. The consolidated reference must survive because the
        loaded entity carries it back through the full-row UPSERT.
        """
        await abseiling_repository.save(
            AbseilingData(
                journal_id=test_journal.id,  # type: ignore[arg-type]
                number_of_abseils=3,
                template_id=test_template.id,
            )
        )

        loaded = await abseiling_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert loaded is not None
        # Edit only an unrelated field, exactly as update_abseiling_type_data does.
        edited = dataclasses.replace(loaded, number_of_abseils=9)
        await abseiling_repository.save(edited)

        found = await abseiling_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found is not None
        assert found.number_of_abseils == 9
        assert str(found.template_id) == str(test_template.id)
