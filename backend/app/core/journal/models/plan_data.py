"""PlanData and PlanDocument entities for the journal domain.

PlanData represents the PLAN journal type data. A journal has the PLAN type if a
row exists in the journal_plan_data table.

PlanDocument represents individual documents linked to a plan, stored in the
journal_plan_documents table with ordering support.
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from .constants import MAX_PLAN_DOCUMENT_TITLE_LENGTH, MAX_PLAN_DOCUMENT_URL_LENGTH
from .exceptions import PlanDataValidationError, PlanDocumentValidationError


@dataclass
class PlanDocument:
    """
    PlanDocument entity for individual documents within a PLAN type journal.

    Represents a document link with metadata, stored in journal_plan_documents table.
    Documents are ordered within a plan using the order field.

    Attributes:
        id: Unique identifier for the document (UUID)
        journal_id: Foreign key to the journal
        url: Document URL (required)
        title: Document title (required)
        description: Optional document description
        order: Order within the plan (for sorting)
        created_at: Creation timestamp
    """

    id: UUID
    journal_id: int
    url: str
    title: str
    order: int
    description: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate plan document properties."""
        self._validate_journal_id()
        self._validate_url()
        self._validate_title()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise PlanDocumentValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_url(self) -> None:
        """Validate URL is provided and within length limit."""
        if not self.url or not self.url.strip():
            raise PlanDocumentValidationError("url", "URL is required")

        if len(self.url) > MAX_PLAN_DOCUMENT_URL_LENGTH:
            raise PlanDocumentValidationError(
                "url", f"URL cannot exceed {MAX_PLAN_DOCUMENT_URL_LENGTH} characters"
            )

    def _validate_title(self) -> None:
        """Validate title is provided and within length limit."""
        if not self.title or not self.title.strip():
            raise PlanDocumentValidationError("title", "Title is required")

        if len(self.title) > MAX_PLAN_DOCUMENT_TITLE_LENGTH:
            raise PlanDocumentValidationError(
                "title",
                f"Title cannot exceed {MAX_PLAN_DOCUMENT_TITLE_LENGTH} characters",
            )


@dataclass
class PlanData:
    """
    PlanData entity for PLAN type journals.

    This entity represents additional data for journals that have the PLAN type.
    A journal is considered to have the PLAN type if a row exists in
    journal_plan_data for that journal_id.

    Plans contain document links for event planning and organization.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        documents: List of plan documents (loaded separately)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    documents: list[PlanDocument] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate plan data properties."""
        self._validate_journal_id()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise PlanDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )
