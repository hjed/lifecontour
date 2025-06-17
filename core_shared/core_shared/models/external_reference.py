"""
External reference SQLAlchemy model.

Tracks references between internal entities and external system entities.
Used to maintain relationships and enable cross-system lookups.
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core_shared.models.base import Base


class ExternalReference(Base):
    """
    Tracks references between internal entities and external system entities.

    This model enables:
    1. Cross-system entity lookups
    2. Relationship tracking between systems
    3. Data consistency validation
    4. Integration health monitoring
    """

    __tablename__ = "external_references"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Internal entity reference
    internal_entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type of internal entity (e.g., 'contact', 'journal_entry', 'event')",
    )
    internal_entity_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="ID of the internal entity"
    )

    # External system reference
    external_system: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Name of the external system (e.g., 'google_contacts', 'immich')",
    )
    external_entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type of external entity (e.g., 'person', 'photo', 'album')",
    )
    external_entity_id: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="External system's ID for this entity"
    )

    # Reference metadata
    reference_data: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Additional reference data as JSON (URLs, metadata, etc.)",
    )

    # Audit timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        comment="When this external reference was created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
        comment="When this external reference was last updated",
    )

    # Indexes for efficient lookups
    __table_args__ = (
        Index(
            "ix_external_references_internal_lookup",
            "internal_entity_type",
            "internal_entity_id",
        ),
        Index(
            "ix_external_references_external_lookup",
            "external_system",
            "external_entity_type",
            "external_entity_id",
        ),
        Index("ix_external_references_system_lookup", "external_system"),
    )

    def __repr__(self) -> str:
        return (
            f"<ExternalReference(id={self.id}, "
            f"internal={self.internal_entity_type}:{self.internal_entity_id}, "
            f"external={self.external_system}:{self.external_entity_id})>"
        )
