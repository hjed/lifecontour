"""
PendingEntityMapping SQLAlchemy model.

Tracks unresolved synchronisation conflicts that arise when a name-based
match produces multiple candidate contacts for a single external entity.
Used by the Immich people sync (and potentially other integrations).
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from core_shared.models.base import Base


class PendingEntityMapping(Base):
    """Tracks unresolved entity mappings (sync conflicts) for manual resolution.

    When inbound sync detects multiple local contacts matching a single
    external entity name, a conflict row is created instead of
    auto-linking.  The user resolves the conflict via the integrations
    dashboard or MCP.

    Attributes:
        user_id: Owner of the conflict.
        integration_source: Integration that detected the conflict
            (e.g. ``"immich"``).
        external_entity_id: External system's entity ID
            (e.g. Immich person UUID).
        external_entity_name: Display name from the external system.
        candidate_contact_ids: JSON array of local contact IDs that
            matched.
        status: ``"unresolved"`` or ``"resolved"``.
        resolved_contact_id: The contact chosen during resolution.
    """

    __tablename__ = "pending_entity_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="User ID who owns this conflict",
    )
    integration_source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Integration source (e.g., 'immich')",
    )
    external_entity_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="External system's entity ID",
    )
    external_entity_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Display name of the external entity",
    )
    candidate_contact_ids: Mapped[list[int]] = mapped_column(
        JSON,
        nullable=False,
        server_default="[]",
        comment="JSON array of candidate contact IDs",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="unresolved",
        comment="Conflict status: 'unresolved' or 'resolved'",
    )
    resolved_contact_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Contact ID chosen for resolution",
    )

    # Audit timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<PendingEntityMapping(id={self.id}, user={self.user_id}, "
            f"source={self.integration_source}, "
            f"external={self.external_entity_id}, "
            f"status={self.status})>"
        )
