"""Integration tests for PlanDataRepository."""

from uuid import uuid4

import pytest
from core_shared.models.journals import PlanData, PlanDocument
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.plan_data_repository import SqlPlanDataRepository


@pytest.mark.integration
class TestSqlPlanDataRepository:
    """Integration tests for SqlPlanDataRepository."""

    async def test_find_by_journal_id_not_found(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test finding plan data that doesn't exist."""
        repo = SqlPlanDataRepository(db_connection)

        result = await repo.find_by_journal_id(sample_journal_id)

        assert result is None

    async def test_save_and_find_plan_data(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test saving and finding plan data."""
        repo = SqlPlanDataRepository(db_connection)

        # Create plan data
        plan_data = PlanData(journal_id=sample_journal_id)

        # Save plan data
        saved = await repo.save(plan_data)

        # Verify saved data
        assert saved.journal_id == sample_journal_id
        assert saved.documents == []
        assert saved.created_at is not None
        assert saved.updated_at is not None

        # Find plan data
        found = await repo.find_by_journal_id(sample_journal_id)

        assert found is not None
        assert found.journal_id == sample_journal_id
        assert found.documents == []
        assert found.created_at == saved.created_at
        assert found.updated_at == saved.updated_at

    async def test_update_plan_data(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test updating existing plan data."""
        repo = SqlPlanDataRepository(db_connection)

        # Create and save initial plan data
        initial_data = PlanData(journal_id=sample_journal_id)
        saved_initial = await repo.save(initial_data)

        # Update plan data (just triggers updated_at change)
        updated_data = PlanData(journal_id=sample_journal_id)
        saved_updated = await repo.save(updated_data)

        # Verify updated data
        assert saved_updated.journal_id == sample_journal_id
        assert saved_updated.created_at == saved_initial.created_at  # Should not change
        assert saved_updated.updated_at is not None
        assert saved_initial.updated_at is not None
        assert saved_updated.updated_at > saved_initial.updated_at  # Should be updated

    async def test_delete_plan_data(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test deleting plan data."""
        repo = SqlPlanDataRepository(db_connection)

        # Create and save plan data
        plan_data = PlanData(journal_id=sample_journal_id)
        await repo.save(plan_data)

        # Verify it exists
        found = await repo.find_by_journal_id(sample_journal_id)
        assert found is not None

        # Delete plan data
        await repo.delete(sample_journal_id)

        # Verify it's deleted
        found_after_delete = await repo.find_by_journal_id(sample_journal_id)
        assert found_after_delete is None

    async def test_save_and_get_documents(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test saving and retrieving plan documents."""
        repo = SqlPlanDataRepository(db_connection)

        # Create plan data first
        plan_data = PlanData(journal_id=sample_journal_id)
        await repo.save(plan_data)

        # Create documents
        doc1 = PlanDocument(
            id=uuid4(),
            journal_id=sample_journal_id,
            url="https://example.com/doc1",
            title="Document 1",
            description="First document",
            order=1,
        )
        doc2 = PlanDocument(
            id=uuid4(),
            journal_id=sample_journal_id,
            url="https://example.com/doc2",
            title="Document 2",
            order=0,  # Should come first due to order
        )

        # Save documents
        saved_doc1 = await repo.save_document(doc1)
        saved_doc2 = await repo.save_document(doc2)

        # Verify saved documents
        assert saved_doc1.id == doc1.id
        assert saved_doc1.title == "Document 1"
        assert saved_doc1.created_at is not None

        assert saved_doc2.id == doc2.id
        assert saved_doc2.title == "Document 2"
        assert saved_doc2.created_at is not None

        # Get documents (should be ordered by order field)
        documents = await repo.get_documents(sample_journal_id)

        assert len(documents) == 2
        assert documents[0].id == doc2.id  # order=0, should come first
        assert documents[1].id == doc1.id  # order=1, should come second

    async def test_find_plan_data_with_documents(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test finding plan data includes associated documents."""
        repo = SqlPlanDataRepository(db_connection)

        # Create plan data
        plan_data = PlanData(journal_id=sample_journal_id)
        await repo.save(plan_data)

        # Create and save document
        document = PlanDocument(
            id=uuid4(),
            journal_id=sample_journal_id,
            url="https://example.com/doc",
            title="Test Document",
            order=0,
        )
        await repo.save_document(document)

        # Find plan data (should include documents)
        found = await repo.find_by_journal_id(sample_journal_id)

        assert found is not None
        assert len(found.documents) == 1
        assert found.documents[0].id == document.id
        assert found.documents[0].title == "Test Document"

    async def test_update_document(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test updating an existing document."""
        repo = SqlPlanDataRepository(db_connection)

        # Create plan data
        plan_data = PlanData(journal_id=sample_journal_id)
        await repo.save(plan_data)

        # Create and save initial document
        document_id = uuid4()
        initial_doc = PlanDocument(
            id=document_id,
            journal_id=sample_journal_id,
            url="https://example.com/initial",
            title="Initial Title",
            order=0,
        )
        await repo.save_document(initial_doc)

        # Update document
        updated_doc = PlanDocument(
            id=document_id,  # Same ID
            journal_id=sample_journal_id,
            url="https://example.com/updated",
            title="Updated Title",
            description="Updated description",
            order=1,
        )
        saved_updated = await repo.save_document(updated_doc)

        # Verify updated document
        assert saved_updated.id == document_id
        assert saved_updated.title == "Updated Title"
        assert saved_updated.url == "https://example.com/updated"
        assert saved_updated.description == "Updated description"
        assert saved_updated.order == 1

        # Verify in database
        documents = await repo.get_documents(sample_journal_id)
        assert len(documents) == 1
        assert documents[0].title == "Updated Title"

    async def test_delete_document(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test deleting a document."""
        repo = SqlPlanDataRepository(db_connection)

        # Create plan data
        plan_data = PlanData(journal_id=sample_journal_id)
        await repo.save(plan_data)

        # Create and save document
        document = PlanDocument(
            id=uuid4(),
            journal_id=sample_journal_id,
            url="https://example.com/doc",
            title="Document to Delete",
            order=0,
        )
        await repo.save_document(document)

        # Verify document exists
        documents = await repo.get_documents(sample_journal_id)
        assert len(documents) == 1

        # Delete document
        await repo.delete_document(document.id)

        # Verify document is deleted
        documents_after_delete = await repo.get_documents(sample_journal_id)
        assert len(documents_after_delete) == 0

    async def test_delete_plan_data_cascades_documents(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test that deleting plan data also deletes associated documents."""
        repo = SqlPlanDataRepository(db_connection)

        # Create plan data
        plan_data = PlanData(journal_id=sample_journal_id)
        await repo.save(plan_data)

        # Create and save document
        document = PlanDocument(
            id=uuid4(),
            journal_id=sample_journal_id,
            url="https://example.com/doc",
            title="Document",
            order=0,
        )
        await repo.save_document(document)

        # Verify document exists
        documents = await repo.get_documents(sample_journal_id)
        assert len(documents) == 1

        # Delete plan data
        await repo.delete(sample_journal_id)

        # Verify documents are also deleted (cascade)
        documents_after_delete = await repo.get_documents(sample_journal_id)
        assert len(documents_after_delete) == 0
