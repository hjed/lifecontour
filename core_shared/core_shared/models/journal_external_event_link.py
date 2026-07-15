"""Shared model for per-calendar journal external event links."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core_shared.models.base import Base

_DB_NOW = "now()"


class ExternalEventLinkSyncCapability(StrEnum):
    """Supported sync capability for an external event link."""

    OUTBOUND = "outbound"
    BIDIRECTIONAL = "bidirectional"


class ExternalEventLinkSyncStatus(StrEnum):
    """Current sync state for an external event link."""

    PENDING = "pending"
    SYNCING = "syncing"
    SYNCED = "synced"
    CONFLICTED = "conflicted"
    CANCELLED = "cancelled"
    ERRORED = "errored"


class JournalExternalEventLink(Base):
    """Per-calendar external event link metadata for EVENT journals."""

    __tablename__ = "journal_external_event_links"

    journal_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("journals.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    calendar_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("calendars.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    external_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recurring_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sync_capability: Mapped[str] = mapped_column(String(32), nullable=False)
    sync_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text(_DB_NOW),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text(_DB_NOW),
        onupdate=text(_DB_NOW),
    )

    __table_args__ = (
        Index(
            "ix_journal_external_event_links_calendar_lookup",
            "calendar_id",
            "journal_id",
        ),
        Index(
            "ix_journal_external_event_links_recurring",
            "calendar_id",
            "recurring_event_id",
            postgresql_where=text("recurring_event_id IS NOT NULL"),
        ),
        CheckConstraint(
            "sync_capability IN ('outbound', 'bidirectional')",
            name="ck_journal_external_event_links_sync_capability",
        ),
        CheckConstraint(
            "sync_status IN ('pending', 'syncing', 'synced', 'conflicted', 'cancelled', 'errored')",
            name="ck_journal_external_event_links_sync_status",
        ),
    )

    def __repr__(self) -> str:
        return (
            "JournalExternalEventLink("
            f"journal_id={self.journal_id}, "
            f"calendar_id={self.calendar_id!r}, "
            f"sync_capability={self.sync_capability!r}, "
            f"sync_status={self.sync_status!r})"
        )
