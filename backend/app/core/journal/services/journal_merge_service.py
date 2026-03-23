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
        self,
        target_id: int,
        source_id: int,
        transaction: AsyncConnection,
        overrides: dict[str, Any] | None = None,
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

        if target.user_id != source.user_id:
            raise JournalMergeConflictError(
                "Cannot merge journals belonging to different users"
            )

        # Ensure atomicity: the repository and this service must use the same transaction
        if (
            hasattr(self.journal_repo, "conn")
            and self.journal_repo.conn is not transaction
        ):
            raise RuntimeError(
                "Merge failed: Repository connection does not match the provided transaction"
            )

        changed_fields: dict[str, Any] = {}
        overrides = overrides or {}

        # Determine default base survivor based on manual journal precedence
        source_cal_res = await transaction.execute(
            text("SELECT 1 FROM journal_calendar_info WHERE journal_id = :id"),
            {"id": source_id},
        )
        target_cal_res = await transaction.execute(
            text("SELECT 1 FROM journal_calendar_info WHERE journal_id = :id"),
            {"id": target_id},
        )
        source_is_event = source_cal_res.fetchone() is not None
        target_is_event = target_cal_res.fetchone() is not None

        # Manual journal precedence: prefer non-event over event journal
        if target_is_event and not source_is_event:
            default_survivor = source
            default_loser = target
        else:
            default_survivor = target
            default_loser = source

        # 1. Base Fields (Overrides > Precedence > Concatenate content)
        new_title = overrides.get("title")
        if new_title:
            if target.title != new_title:
                target.title = new_title
                changed_fields["title"] = new_title
        else:
            # Fallback to default precedence if no override
            if source.title and target.title and source.title != target.title:
                if target.title != default_survivor.title:
                    target.title = default_survivor.title
                    changed_fields["title"] = default_survivor.title
                logger.debug(
                    f"Merge title conflict resolved by keeping '{target.title}' vs '{default_loser.title}'"
                )
            elif source.title and not target.title:
                target.title = source.title
                changed_fields["title"] = source.title

        new_date_range = overrides.get("event_date_range")
        if new_date_range:
            from datetime import datetime

            if isinstance(new_date_range, dict):
                start_dt = new_date_range["start"]
                if isinstance(start_dt, str):
                    start_dt = datetime.fromisoformat(start_dt)
                end_dt = new_date_range["end"]
                if isinstance(end_dt, str):
                    end_dt = datetime.fromisoformat(end_dt)
                new_event_date_range = type(target.event_date_range)(
                    start=start_dt, end=end_dt
                )
            else:
                new_event_date_range = new_date_range

            if target.event_date_range != new_event_date_range:
                target.event_date_range = new_event_date_range
                changed_fields["event_date_range"] = {
                    "start": target.event_date_range.start.isoformat(),
                    "end": target.event_date_range.end.isoformat(),
                }
        else:
            if (
                source.event_date_range
                and target.event_date_range
                and source.event_date_range != target.event_date_range
            ):
                if target.event_date_range != default_survivor.event_date_range:
                    target.event_date_range = default_survivor.event_date_range
                    changed_fields["event_date_range"] = {
                        "start": target.event_date_range.start.isoformat(),
                        "end": target.event_date_range.end.isoformat(),
                    }
                logger.debug(
                    f"Merge date conflict resolved by keeping '{target.event_date_range}' vs '{default_loser.event_date_range}'"
                )
            elif source.event_date_range and not target.event_date_range:
                target.event_date_range = source.event_date_range
                changed_fields["event_date_range"] = {
                    "start": source.event_date_range.start.isoformat(),
                    "end": source.event_date_range.end.isoformat(),
                }

        new_content = overrides.get("content")
        if new_content:
            if target.content != new_content:
                target.content = new_content
                changed_fields["content"] = new_content
        else:
            if source.content and target.content and source.content != target.content:
                target.content = f"{target.content}\n\n---\n\n{source.content}"
                changed_fields["content"] = target.content
            elif source.content and not target.content:
                target.content = source.content
                changed_fields["content"] = target.content

        # Save target core fields regardless to ensure they are updated
        # But only track them in changed_fields if they changed
        await self.journal_repo.save(target)

        # Prevent cycles: if target is a descendant of source, reject
        ancestors = await self.journal_repo.get_ancestors(target_id)
        if any(a.id == source_id for a in ancestors):
            raise JournalMergeConflictError(
                "Target journal cannot be a descendant of the source journal"
            )

        # 2. Re-parent hierarchy
        # Do not reparent the target journal to itself if it was a child of the source
        await transaction.execute(
            text(
                "UPDATE journals SET parent_id = :target_id WHERE parent_id = :source_id AND id != :target_id"
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
                INSERT INTO journal_external_event_links (journal_id, calendar_id, external_event_id, updated_at, sync_capability, sync_status)
                SELECT :target_id, calendar_id, external_event_id, updated_at, sync_capability, sync_status
                FROM journal_external_event_links source_links
                WHERE journal_id = :source_id
                AND NOT EXISTS (
                    SELECT 1 FROM journal_external_event_links target_links
                    WHERE target_links.journal_id = :target_id
                    AND target_links.calendar_id IS NOT DISTINCT FROM source_links.calendar_id
                    AND target_links.external_event_id IS NOT DISTINCT FROM source_links.external_event_id
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

                # Fetch overrides for this type
                # _JOURNAL_TYPE_TABLE_MAP Maps Enum names to table names. Keys might be uppercase or lowercase.
                # We need all matching Enum names for this table name to check for overrides.
                type_enum_names = [
                    k
                    for k, v in _JOURNAL_TYPE_TABLE_MAP.items()
                    if v == table_name and k.isupper()
                ]
                type_overrides = {}
                for tenum in type_enum_names:
                    type_overrides.update(overrides.get("type_data", {}).get(tenum, {}))

                for col in source_dict.keys():
                    if col in ("id", "journal_id"):
                        continue

                    if col in type_overrides:
                        if type_overrides[col] != target_dict[col]:
                            updates.append(f"{col} = :{col}")
                            update_params[col] = type_overrides[col]
                        continue

                    s_val = source_dict[col]
                    t_val = target_dict[col]

                    # If the source row is explicitly chosen as default survivor based on precedence,
                    # we should override target values with source values
                    if (
                        default_survivor is source
                        and s_val is not None
                        and t_val != s_val
                    ):
                        updates.append(f"{col} = :{col}")
                        update_params[col] = s_val
                    # Otherwise keep concatenation/merging logic (fill nulls)
                    elif s_val is not None and t_val is None:
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

        await self.journal_repo.delete(source_id)

        # Deleting source can have many cascaded foreign key drops.
        # For merge-deletions, do not publish external identifiers so that
        # external integrations (e.g. Google Calendar) do not delete events
        # that have been preserved on the target journal.
        await self.event_publisher.publish(
            JournalDeleted(
                source_id,
                user_id=source.user_id,
                external_identifiers={},
                transaction=transaction,
            )
        )

        logger.info(
            "Journals merged successfully", target_id=target_id, source_id=source_id
        )
        return target
