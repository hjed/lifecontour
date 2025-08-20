"""
Outbox Event model for transactional outbox pattern.

This model enables reliable event publishing by storing events in the same
database transaction as the business data changes.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID

from .base import Base


class OutboxEvent(Base):
    """
    Outbox event for transactional outbox pattern.

    Events are stored in the same transaction as business data changes,
    then processed asynchronously by a separate event publisher.
    """

    __tablename__ = "outbox_events"

    id = Column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid4, nullable=False
    )

    event_type = Column(
        String(100),
        nullable=False,
        comment="Type of event (e.g., 'contact.created', 'sync.completed')",
    )

    aggregate_id = Column(
        PostgresUUID(as_uuid=True),
        nullable=True,
        comment="ID of the entity that changed",
    )

    event_data = Column(
        JSONB, nullable=False, comment="JSON payload with event details"
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
        comment="When the event was created",
    )

    processed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the event was successfully processed",
    )

    retry_count = Column(
        Integer,
        server_default=text("0"),
        nullable=False,
        comment="Number of processing attempts",
    )

    max_retries = Column(
        Integer,
        server_default=text("3"),
        nullable=False,
        comment="Maximum number of retry attempts",
    )

    error_message = Column(
        Text, nullable=True, comment="Last error message if processing failed"
    )

    def __repr__(self) -> str:
        """String representation of the outbox event."""
        return (
            f"<OutboxEvent(id={self.id}, event_type='{self.event_type}', "
            f"aggregate_id={self.aggregate_id}, processed_at={self.processed_at})>"
        )

    @classmethod
    def create_contact_sync_event(
        cls,
        contact_data: dict[str, Any],
        integration_source: str,
        external_id: str,
        sync_type: str = "created",
    ) -> "OutboxEvent":
        """
        Create an outbox event for contact synchronization.

        Args:
            contact_data: Contact data from external system
            integration_source: Source integration (e.g., 'google_contacts')
            external_id: External system's contact ID
            sync_type: Type of sync operation ('created', 'updated', 'deleted')

        Returns:
            OutboxEvent instance ready to be saved
        """
        return cls(
            event_type=f"contact.{sync_type}",
            event_data={
                "integration_source": integration_source,
                "external_id": external_id,
                "contact_data": contact_data,
                "sync_timestamp": datetime.now(UTC).isoformat(),
                "sync_type": sync_type,
            },
        )

    @classmethod
    def create_sync_completed_event(
        cls, integration_source: str, google_account_email: str, metrics: dict[str, Any]
    ) -> "OutboxEvent":
        """
        Create an outbox event for sync completion.

        Args:
            integration_source: Source integration (e.g., 'google_contacts')
            google_account_email: Google account that was synced
            metrics: Sync metrics and results

        Returns:
            OutboxEvent instance ready to be saved
        """
        return cls(
            event_type="sync.completed",
            event_data={
                "integration_source": integration_source,
                "google_account_email": google_account_email,
                "metrics": metrics,
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )

    def is_failed(self) -> bool:
        """Check if the event has failed processing."""
        return bool(self.retry_count >= self.max_retries and self.processed_at is None)

    def can_retry(self) -> bool:
        """Check if the event can be retried."""
        return bool(self.retry_count < self.max_retries and self.processed_at is None)
