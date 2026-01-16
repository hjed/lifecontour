"""
Sync job SQLAlchemy model.

Tracks sync job history for integration workers.
Provides persistent storage for job status, progress, and results.
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core_shared.models.base import Base


class SyncJobStatus(Enum):
    """Status of a sync job."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SyncType(Enum):
    """Type of sync operation."""

    SMART = "smart"
    FULL = "full"


class SyncJob(Base):
    """
    Tracks sync job history for integration workers.

    This model provides:
    1. Persistent job history beyond Redis TTL
    2. User-specific job tracking and filtering
    3. Progress and result tracking
    4. Error logging and debugging
    """

    __tablename__ = "sync_jobs"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Job identification
    job_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="ARQ job ID for tracking in Redis",
    )

    # User and integration tracking
    user_id: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="User who initiated the sync",
    )
    integration_source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Integration source (e.g., 'google_contacts')",
    )

    # Sync configuration
    sync_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Type of sync: 'smart', 'full'",
    )

    # Job status and timing
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="Job status: 'queued', 'running', 'completed', 'failed', 'cancelled'",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=True,
        comment="When the job was created",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the job started processing",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the job completed",
    )

    # Error tracking
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error message if job failed",
    )

    # Progress and results
    contacts_processed: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of contacts processed",
    )
    contacts_created: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of contacts created",
    )
    contacts_updated: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of contacts updated",
    )
    contacts_deleted: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of contacts deleted",
    )
    progress: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Progress percentage (0-100)",
    )

    # Audit tracking
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        comment="Last update timestamp",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_sync_jobs_status",
        ),
        CheckConstraint(
            "sync_type IN ('smart', 'full')",
            name="ck_sync_jobs_sync_type",
        ),
        CheckConstraint(
            "progress IS NULL OR (progress >= 0 AND progress <= 100)",
            name="ck_sync_jobs_progress_range",
        ),
    )
