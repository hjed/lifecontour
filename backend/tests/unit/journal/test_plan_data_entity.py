"""Unit tests for PlanData and PlanDocument entities (PLAN type)."""

from uuid import uuid4

import pytest

from app.core.journal.models.constants import (
    MAX_PLAN_DOCUMENT_TITLE_LENGTH,
    MAX_PLAN_DOCUMENT_URL_LENGTH,
)
from app.core.journal.models.exceptions import (
    PlanDataValidationError,
    PlanDocumentValidationError,
)
from app.core.journal.models.plan_data import PlanData, PlanDocument


@pytest.mark.unit
class TestPlanData:
    """Test PlanData entity."""

    def test_create_plan_data_minimal(self):
        """Test creating plan data with minimal required fields."""
        plan_data = PlanData(journal_id=1)

        assert plan_data.journal_id == 1
        assert plan_data.documents == []

    def test_create_plan_data_with_documents(self):
        """Test creating plan data with documents."""
        doc = PlanDocument(
            id=uuid4(),
            journal_id=1,
            url="https://example.com/doc.pdf",
            title="Planning Document",
            order=0,
        )
        plan_data = PlanData(journal_id=1, documents=[doc])

        assert len(plan_data.documents) == 1
        assert plan_data.documents[0].url == "https://example.com/doc.pdf"


@pytest.mark.unit
class TestPlanDataValidation:
    """Test PlanData validation."""

    def test_invalid_journal_id_zero_raises_error(self):
        """Test that journal_id of 0 raises error."""
        with pytest.raises(
            PlanDataValidationError,
            match="Journal ID must be a positive integer",
        ):
            PlanData(journal_id=0)

    def test_invalid_journal_id_negative_raises_error(self):
        """Test that negative journal_id raises error."""
        with pytest.raises(
            PlanDataValidationError,
            match="Journal ID must be a positive integer",
        ):
            PlanData(journal_id=-1)


@pytest.mark.unit
class TestPlanDocument:
    """Test PlanDocument entity."""

    def test_create_plan_document_minimal(self):
        """Test creating plan document with minimal required fields."""
        doc = PlanDocument(
            id=uuid4(),
            journal_id=1,
            url="https://example.com/doc.pdf",
            title="My Document",
            order=0,
        )

        assert doc.journal_id == 1
        assert doc.url == "https://example.com/doc.pdf"
        assert doc.title == "My Document"
        assert doc.description is None
        assert doc.order == 0

    def test_create_plan_document_with_description(self):
        """Test creating plan document with description."""
        doc = PlanDocument(
            id=uuid4(),
            journal_id=1,
            url="https://example.com/doc.pdf",
            title="My Document",
            description="This is a detailed description",
            order=0,
        )

        assert doc.description == "This is a detailed description"


@pytest.mark.unit
class TestPlanDocumentValidation:
    """Test PlanDocument validation."""

    def test_invalid_journal_id_raises_error(self):
        """Test that invalid journal_id raises error."""
        with pytest.raises(
            PlanDocumentValidationError,
            match="Journal ID must be a positive integer",
        ):
            PlanDocument(
                id=uuid4(),
                journal_id=0,
                url="https://example.com",
                title="Doc",
                order=0,
            )

    def test_empty_url_raises_error(self):
        """Test that empty URL raises error."""
        with pytest.raises(
            PlanDocumentValidationError,
            match="URL is required",
        ):
            PlanDocument(
                id=uuid4(),
                journal_id=1,
                url="",
                title="Doc",
                order=0,
            )

    def test_url_too_long_raises_error(self):
        """Test that URL exceeding max length raises error."""
        long_url = "https://example.com/" + "a" * MAX_PLAN_DOCUMENT_URL_LENGTH
        with pytest.raises(
            PlanDocumentValidationError,
            match=f"URL cannot exceed {MAX_PLAN_DOCUMENT_URL_LENGTH}",
        ):
            PlanDocument(
                id=uuid4(),
                journal_id=1,
                url=long_url,
                title="Doc",
                order=0,
            )

    def test_empty_title_raises_error(self):
        """Test that empty title raises error."""
        with pytest.raises(
            PlanDocumentValidationError,
            match="Title is required",
        ):
            PlanDocument(
                id=uuid4(),
                journal_id=1,
                url="https://example.com",
                title="",
                order=0,
            )

    def test_title_too_long_raises_error(self):
        """Test that title exceeding max length raises error."""
        long_title = "a" * (MAX_PLAN_DOCUMENT_TITLE_LENGTH + 1)
        with pytest.raises(
            PlanDocumentValidationError,
            match=f"Title cannot exceed {MAX_PLAN_DOCUMENT_TITLE_LENGTH}",
        ):
            PlanDocument(
                id=uuid4(),
                journal_id=1,
                url="https://example.com",
                title=long_title,
                order=0,
            )
