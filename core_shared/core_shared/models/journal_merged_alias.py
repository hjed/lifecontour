"""Shared model for the inbound records a journal absorbed by merging."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core_shared.models.base import Base


class JournalMergedAlias(Base):
    """An inbound record a merge absorbed, kept so the sync still knows it.

    A merge deletes the source journal, and with it any external link the
    target could not take over — a second event in a calendar the target is
    already linked in, a rival Strava activity in a replace merge. Without a
    trace of it, the next sync would import that record again as a new
    journal. An alias is that trace: it says "this record is ``journal_id``".

    It is **recognition only**. Nothing is ever pushed to an aliased record;
    the outbound sync reads links, never this table. Read and write it through
    ``core_shared.repositories.merged_alias_repository.MergedAliasRepository``.

    ``integration_source``/``external_id`` are the link store's names (see
    ``core_shared.merged_alias_keys``). ``calendar_id``, ``external_identity``
    and ``recurring_event_id`` are carried over from a calendar link so the
    alias can be recognised from another calendar and deleted upstream with
    its journal.
    """

    __tablename__ = "journal_merged_aliases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    journal_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("journals.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    integration_source: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    calendar_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("calendars.id", ondelete="SET NULL"),
        nullable=True,
    )
    external_identity: Mapped[str | None] = mapped_column(String(512), nullable=True)
    recurring_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "integration_source",
            "external_id",
            name="uq_journal_merged_aliases_user_source_external",
        ),
        Index("ix_journal_merged_aliases_journal", "journal_id"),
        Index(
            "ix_journal_merged_aliases_identity",
            "user_id",
            "external_identity",
            postgresql_where=text("external_identity IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return (
            "JournalMergedAlias("
            f"journal_id={self.journal_id}, "
            f"integration_source={self.integration_source!r}, "
            f"external_id={self.external_id!r})"
        )
