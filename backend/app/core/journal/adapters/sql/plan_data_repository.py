"""SQL implementation of PlanDataRepository."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.exceptions import (
    PlanDataValidationError,
    PlanDocumentValidationError,
)
from app.core.journal.models.plan_data import PlanData, PlanDocument
from app.core.journal.models.repositories import PlanDataRepository


class SqlPlanDataRepository(PlanDataRepository):
    """
    SQL implementation of PlanDataRepository using SQLAlchemy Core.

    Uses explicit SQL queries for clarity and performance.
    Handles the journal_plan_data and journal_plan_documents table operations.
    """

    def __init__(self, connection: AsyncConnection):
        """
        Initialize the repository with a database connection.

        Args:
            connection: SQLAlchemy async connection
        """
        self.connection = connection

    async def find_by_journal_id(self, journal_id: int) -> PlanData | None:
        """
        Find plan data by journal ID, including associated documents.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The PlanData with documents if found (journal has PLAN type), None otherwise
        """
        # First check if plan data exists
        plan_query = text("""
            SELECT journal_id, created_at, updated_at
            FROM journal_plan_data
            WHERE journal_id = :journal_id
        """)

        result = await self.connection.execute(plan_query, {"journal_id": journal_id})
        plan_row = result.fetchone()

        if plan_row is None:
            return None

        # Get associated documents
        documents = await self.get_documents(journal_id)

        return PlanData(
            journal_id=plan_row.journal_id,
            documents=documents,
            created_at=plan_row.created_at,
            updated_at=plan_row.updated_at,
        )

    async def save(self, plan_data: PlanData) -> PlanData:
        """
        Save plan data (insert or update).

        This effectively adds or updates the PLAN type for a journal.
        Documents are saved separately.

        Args:
            plan_data: The plan data to save

        Returns:
            The saved plan data with updated timestamps

        Raises:
            PlanDataValidationError: If database constraints are violated
        """
        now = datetime.utcnow()

        # Check if record exists
        existing = await self.find_by_journal_id(plan_data.journal_id)

        try:
            if existing is None:
                # Insert new record
                query = text("""
                    INSERT INTO journal_plan_data 
                    (journal_id, created_at, updated_at)
                    VALUES (:journal_id, :created_at, :updated_at)
                """)

                await self.connection.execute(
                    query,
                    {
                        "journal_id": plan_data.journal_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                )

                return PlanData(
                    journal_id=plan_data.journal_id,
                    documents=plan_data.documents,
                    created_at=now,
                    updated_at=now,
                )
            else:
                # Update existing record
                query = text("""
                    UPDATE journal_plan_data
                    SET updated_at = :updated_at
                    WHERE journal_id = :journal_id
                """)

                await self.connection.execute(
                    query,
                    {
                        "journal_id": plan_data.journal_id,
                        "updated_at": now,
                    },
                )

                return PlanData(
                    journal_id=plan_data.journal_id,
                    documents=plan_data.documents,
                    created_at=existing.created_at,
                    updated_at=now,
                )

        except IntegrityError as e:
            raise PlanDataValidationError(
                "database", f"Database constraint violation: {e}"
            ) from e

    async def delete(self, journal_id: int) -> None:
        """
        Delete plan data by journal ID.

        This effectively removes the PLAN type from a journal.
        Associated documents are cascade deleted.

        Args:
            journal_id: The journal ID to delete plan data for
        """
        query = text("""
            DELETE FROM journal_plan_data
            WHERE journal_id = :journal_id
        """)

        await self.connection.execute(query, {"journal_id": journal_id})

    async def save_document(self, document: PlanDocument) -> PlanDocument:
        """
        Save a plan document (insert or update).

        Args:
            document: The plan document to save

        Returns:
            The saved plan document with updated timestamps

        Raises:
            PlanDocumentValidationError: If database constraints are violated
        """
        now = datetime.utcnow()

        try:
            # Use UPSERT (INSERT ... ON CONFLICT) for PostgreSQL
            query = text("""
                INSERT INTO journal_plan_documents 
                (id, journal_id, url, title, description, "order", created_at)
                VALUES (:id, :journal_id, :url, :title, :description, :order, :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    url = EXCLUDED.url,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    "order" = EXCLUDED."order"
            """)

            await self.connection.execute(
                query,
                {
                    "id": document.id,
                    "journal_id": document.journal_id,
                    "url": document.url,
                    "title": document.title,
                    "description": document.description,
                    "order": document.order,
                    "created_at": document.created_at or now,
                },
            )

            return PlanDocument(
                id=document.id,
                journal_id=document.journal_id,
                url=document.url,
                title=document.title,
                description=document.description,
                order=document.order,
                created_at=document.created_at or now,
            )

        except IntegrityError as e:
            raise PlanDocumentValidationError(
                "database", f"Database constraint violation: {e}"
            ) from e

    async def delete_document(self, document_id: UUID) -> None:
        """
        Delete a plan document by ID.

        Args:
            document_id: The document UUID to delete
        """
        query = text("""
            DELETE FROM journal_plan_documents
            WHERE id = :document_id
        """)

        await self.connection.execute(query, {"document_id": document_id})

    async def get_documents(self, journal_id: int) -> list[PlanDocument]:
        """
        Get all documents for a plan, ordered by order field.

        Args:
            journal_id: The journal ID to get documents for

        Returns:
            List of plan documents in order
        """
        query = text("""
            SELECT id, journal_id, url, title, description, "order", created_at
            FROM journal_plan_documents
            WHERE journal_id = :journal_id
            ORDER BY "order", created_at
        """)

        result = await self.connection.execute(query, {"journal_id": journal_id})
        rows = result.fetchall()

        return [
            PlanDocument(
                id=row.id,
                journal_id=row.journal_id,
                url=row.url,
                title=row.title,
                description=row.description,
                order=row.order,
                created_at=row.created_at,
            )
            for row in rows
        ]
