"""Service for merging journals."""

from typing import Any

import structlog
from core_shared.models.journals import (
    Journal,
    JournalNotFoundError,
)
from core_shared.models.journals.exceptions import JournalMergeConflictError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import _JOURNAL_TYPE_TABLE_MAP
from app.core.journal.models.events import (
    JournalDeleted,
    JournalUpdated,
)
from app.core.journal.models.repositories import JournalRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher

logger = structlog.get_logger(__name__)


class JournalMergeService:
    """Service for handling journal merges in Phase 1."""

    def __init__(
        self,
        journal_repo: JournalRepository,
        event_publisher: OutboxEventPublisher,
    ):
        self.journal_repo = journal_repo
        self.event_publisher = event_publisher

    async def merge_journals(
        self, target_id: int, source_id: int, transaction: AsyncConnection
    ) -> Journal:
        """
        Merge source_id journal into target_id journal.
        Returns the merged target journal.
        Deletes the source journal.
        """
        if target_id == source_id:
            raise JournalMergeConflictError("Cannot merge a journal into itself")

        target = await self.journal_repo.find_by_id(target_id)
        source = await self.journal_repo.find_by_id(source_id)

        if not target:
            raise JournalNotFoundError(target_id)
        if not source:
            raise JournalNotFoundError(source_id)

        changed_fields: dict[str, Any] = {}

        # 1. Base Fields (prefer non-empty, concatenate content)
        if source.title and target.title and source.title != target.title:
            raise JournalMergeConflictError(
                f"Conflicting titles: '{target.title}' vs '{source.title}'"
            )
        elif source.title and not target.title:
            target.title = source.title
            changed_fields["title"] = source.title

        if (
            source.event_date_range
            and target.event_date_range
            and source.event_date_range != target.event_date_range
        ):
            raise JournalMergeConflictError("Conflicting event date ranges")
        elif source.event_date_range and not target.event_date_range:
            target.event_date_range = source.event_date_range
            changed_fields["event_date_range"] = source.event_date_range

        if source.content and target.content and source.content != target.content:
            target.content = f"{target.content}\n\n---\n\n{source.content}"
            changed_fields["content"] = target.content
        elif source.content and not target.content:
            target.content = source.content
            changed_fields["content"] = target.content

        # Save target core fields regardless to ensure they are updated
        # But only track them in changed_fields if they changed
        await self.journal_repo.save(target)

        # 2. Re-parent hierarchy
        await transaction.execute(
            text(
                "UPDATE journals SET parent_id = :target_id WHERE parent_id = :source_id"
            ),
            {"target_id": target_id, "source_id": source_id},
        )

        # Type entries are implicit from the tables themselves so we do not need a journal_types table

        # 4. Move tags (ignore duplicates)
        await transaction.execute(
            text("""
                INSERT INTO journal_tag_assignments (journal_id, tag_id)
                SELECT :target_id, tag_id FROM journal_tag_assignments WHERE journal_id = :source_id
                ON CONFLICT (journal_id, tag_id) DO NOTHING
            """),
            {"target_id": target_id, "source_id": source_id},
        )

        # 5. Move Contact Relationships
        await transaction.execute(
            text("""
                INSERT INTO journal_contact_relationships (journal_id, contact_id, relationship_type)
                SELECT :target_id, contact_id, relationship_type
                FROM journal_contact_relationships source_rels
                WHERE journal_id = :source_id
                AND NOT EXISTS (
                    SELECT 1 FROM journal_contact_relationships target_rels
                    WHERE target_rels.journal_id = :target_id
                    AND target_rels.contact_id = source_rels.contact_id
                    AND target_rels.relationship_type = source_rels.relationship_type
                )
            """),
            {"target_id": target_id, "source_id": source_id},
        )

        # 6. Move External Links (deduplicate)
        await transaction.execute(
            text("""
                INSERT INTO journal_external_event_links (journal_id, calendar_id, external_event_id, updated_at)
                SELECT :target_id, calendar_id, external_event_id, updated_at
                FROM journal_external_event_links source_links
                WHERE journal_id = :source_id
                AND NOT EXISTS (
                    SELECT 1 FROM journal_external_event_links target_links
                    WHERE target_links.journal_id = :target_id
                    AND target_links.calendar_id = source_links.calendar_id
                    AND target_links.external_event_id = source_links.external_event_id
                )
            """),
            {"target_id": target_id, "source_id": source_id},
        )

        # 7. Type Data Scalable merge
        table_names = set(_JOURNAL_TYPE_TABLE_MAP.values())
        for table_name in table_names:
            source_row_res = await transaction.execute(
                text(f"SELECT * FROM {table_name} WHERE journal_id = :source_id"),
                {"source_id": source_id},
            )
            source_row = source_row_res.fetchone()
            if not source_row:
                continue

            target_row_res = await transaction.execute(
                text(f"SELECT * FROM {table_name} WHERE journal_id = :target_id"),
                {"target_id": target_id},
            )
            target_row = target_row_res.fetchone()

            if not target_row:
                await transaction.execute(
                    text(
                        f"UPDATE {table_name} SET journal_id = :target_id WHERE journal_id = :source_id"
                    ),
                    {"target_id": target_id, "source_id": source_id},
                )
                changed_fields[f"{table_name}_added"] = True
            else:
                source_dict = source_row._mapping
                target_dict = target_row._mapping
                updates = []
                update_params = {"target_id": target_id}

                for col in source_dict.keys():
                    if col in ("id", "journal_id"):
                        continue
                    s_val = source_dict[col]
                    t_val = target_dict[col]
                    if s_val is not None and t_val is None:
                        updates.append(f"{col} = :{col}")
                        update_params[col] = s_val

                if updates:
                    set_clause = ", ".join(updates)
                    await transaction.execute(
                        text(
                            f"UPDATE {table_name} SET {set_clause} WHERE journal_id = :target_id"
                        ),
                        update_params,
                    )
                    changed_fields[f"{table_name}_updated"] = True

                await transaction.execute(
                    text(f"DELETE FROM {table_name} WHERE journal_id = :source_id"),
                    {"source_id": source_id},
                )

        if changed_fields:
            await self.event_publisher.publish(
                JournalUpdated(target_id, changed_fields, transaction=transaction)
            )
        else:
            await self.event_publisher.publish(
                JournalUpdated(
                    target_id, {"relationships_merged": True}, transaction=transaction
                )
            )

        stmt = text("""
            SELECT jeel.external_event_id, c.google_calendar_id
            FROM journal_external_event_links jeel
            JOIN calendars c ON jeel.calendar_id = c.id
            WHERE jeel.journal_id = :source_id AND jeel.external_event_id IS NOT NULL
        """)
        result = await transaction.execute(stmt, {"source_id": source_id})
        external_identifiers: dict[str, list[dict[str, Any]]] = {}
        for row in result.fetchall():
            if "google" not in external_identifiers:
                external_identifiers["google"] = []
            external_identifiers["google"].append(
                {
                    "external_event_id": row.external_event_id,
                    "google_calendar_id": row.google_calendar_id,
                }
            )

        await self.journal_repo.delete(source_id)

        # Deleting source can have many cascaded foreign key drops
        # but the outbox logic wants external_ids published to Meilisearch
        await self.event_publisher.publish(
            JournalDeleted(
                source_id,
                user_id=source.user_id,
                external_identifiers=external_identifiers,
                transaction=transaction,
            )
        )

        logger.info(
            "Journals merged successfully", target_id=target_id, source_id=source_id
        )
        return target
