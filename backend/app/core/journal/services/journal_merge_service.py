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

        self._validate_merge_preconditions(
            target, source, target_id, source_id, transaction
        )

        # for type checking, we can assert target and source are not None here
        # because _validate_merge_preconditions raises if they are
        assert target is not None
        assert source is not None

        # Prevent cycles: if target is a descendant of source, reject
        ancestors = await self.journal_repo.get_ancestors(target_id)
        if any(a.id == source_id for a in ancestors):
            raise JournalMergeConflictError(
                "Target journal cannot be a descendant of the source journal"
            )

        changed_fields: dict[str, Any] = {}
        overrides = overrides or {}

        # Determine default base survivor based on manual journal precedence
        default_survivor, default_loser = await self._determine_precedence(
            target_id, source_id, target, source, transaction
        )

        # 1. Base Fields (Overrides > Precedence > Concatenate content)
        self._apply_base_field_overrides(
            target, source, default_survivor, default_loser, overrides, changed_fields
        )

        # Save target core fields regardless to ensure they are updated
        await self.journal_repo.save(target)

        # 2. Re-parent hierarchy
        await self._reparent_hierarchy(target_id, source_id, transaction)

        # 3. Move routes
        await self._move_routes(target_id, source_id, transaction)

        # 4. Move tags (ignore duplicates)
        await self._move_tags(target_id, source_id, transaction)

        # 5. Move Contact Relationships
        await self._move_contact_relationships(target_id, source_id, transaction)

        # 6. Move External Links (deduplicate)
        await self._move_external_links(target_id, source_id, transaction)

        # 7. Type Data Scalable merge
        await self._merge_type_data(
            target_id,
            source_id,
            default_survivor,
            source,
            overrides,
            changed_fields,
            transaction,
        )

        # 8. Publish Events & Cleanup Source
        await self._publish_events_and_cleanup(
            target_id, source_id, source, changed_fields, transaction
        )

        logger.info(
            "Journals merged successfully", target_id=target_id, source_id=source_id
        )
        return target

    def _validate_merge_preconditions(
        self,
        target: Journal | None,
        source: Journal | None,
        target_id: int,
        source_id: int,
        transaction: AsyncConnection,
    ) -> None:
        if not target:
            raise JournalNotFoundError(target_id)
        if not source:
            raise JournalNotFoundError(source_id)

        if target.user_id != source.user_id:
            raise JournalMergeConflictError(
                "Cannot merge journals belonging to different users"
            )

        if (
            hasattr(self.journal_repo, "conn")
            and self.journal_repo.conn is not transaction
        ):
            raise RuntimeError(
                "Merge failed: Repository connection does not match the provided transaction"
            )

    async def _determine_precedence(
        self,
        target_id: int,
        source_id: int,
        target: Journal,
        source: Journal,
        transaction: AsyncConnection,
    ) -> tuple[Journal, Journal]:
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

        if target_is_event and not source_is_event:
            return source, target
        return target, source

    def _apply_base_field_overrides(
        self,
        target: Journal,
        source: Journal,
        default_survivor: Journal,
        default_loser: Journal,
        overrides: dict[str, Any],
        changed_fields: dict[str, Any],
    ) -> None:
        self._apply_title_override(
            target,
            source,
            default_survivor,
            default_loser,
            overrides.get("title"),
            changed_fields,
        )
        self._apply_date_range_override(
            target,
            source,
            default_survivor,
            default_loser,
            overrides.get("event_date_range"),
            changed_fields,
        )
        self._apply_content_override(
            target, source, overrides.get("content"), changed_fields
        )

    def _apply_title_override(
        self,
        target: Journal,
        source: Journal,
        default_survivor: Journal,
        default_loser: Journal,
        new_title: Any,
        changed_fields: dict[str, Any],
    ) -> None:
        if new_title:
            if target.title != new_title:
                target.title = new_title
                changed_fields["title"] = new_title
        else:
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

    def _apply_date_range_override(
        self,
        target: Journal,
        source: Journal,
        default_survivor: Journal,
        default_loser: Journal,
        new_date_range: Any,
        changed_fields: dict[str, Any],
    ) -> None:
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

    def _apply_content_override(
        self,
        target: Journal,
        source: Journal,
        new_content: Any,
        changed_fields: dict[str, Any],
    ) -> None:
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

    async def _reparent_hierarchy(
        self, target_id: int, source_id: int, transaction: AsyncConnection
    ) -> None:
        await transaction.execute(
            text(
                "UPDATE journals SET parent_id = :target_id WHERE parent_id = :source_id AND id != :target_id"
            ),
            {"target_id": target_id, "source_id": source_id},
        )

    async def _move_routes(
        self, target_id: int, source_id: int, transaction: AsyncConnection
    ) -> None:
        await transaction.execute(
            text(
                "UPDATE routes SET journal_id = :target_id WHERE journal_id = :source_id"
            ),
            {"target_id": target_id, "source_id": source_id},
        )

    async def _move_tags(
        self, target_id: int, source_id: int, transaction: AsyncConnection
    ) -> None:
        await transaction.execute(
            text("""
                INSERT INTO journal_tag_assignments (journal_id, tag_id)
                SELECT :target_id, tag_id FROM journal_tag_assignments WHERE journal_id = :source_id
                ON CONFLICT (journal_id, tag_id) DO NOTHING
            """),
            {"target_id": target_id, "source_id": source_id},
        )

    async def _move_contact_relationships(
        self, target_id: int, source_id: int, transaction: AsyncConnection
    ) -> None:
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

    async def _move_external_links(
        self, target_id: int, source_id: int, transaction: AsyncConnection
    ) -> None:
        await transaction.execute(
            text("""
                WITH removed AS (
                    DELETE FROM journal_external_event_links
                    WHERE journal_id = :source_id
                    RETURNING calendar_id, external_event_id, external_version,
                            sync_capability, sync_status, created_at, updated_at
                )
                INSERT INTO journal_external_event_links
                    (journal_id, calendar_id, external_event_id, external_version,
                     sync_capability, sync_status, created_at, updated_at)
                SELECT :target_id, calendar_id, external_event_id, external_version,
                       sync_capability, sync_status, created_at, updated_at
                FROM removed
                ON CONFLICT (journal_id, calendar_id) DO NOTHING
            """),
            {"target_id": target_id, "source_id": source_id},
        )

    async def _merge_type_data(
        self,
        target_id: int,
        source_id: int,
        default_survivor: Journal,
        source: Journal,
        overrides: dict[str, Any],
        changed_fields: dict[str, Any],
        transaction: AsyncConnection,
    ) -> None:
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
                await self._transfer_new_type_data(
                    table_name, target_id, source_id, changed_fields, transaction
                )
            else:
                await self._merge_existing_type_data(
                    table_name,
                    target_id,
                    source_id,
                    target_row,
                    source_row,
                    default_survivor,
                    source,
                    overrides,
                    changed_fields,
                    transaction,
                )

    async def _transfer_new_type_data(
        self,
        table_name: str,
        target_id: int,
        source_id: int,
        changed_fields: dict[str, Any],
        transaction: AsyncConnection,
    ) -> None:
        await transaction.execute(
            text(
                f"UPDATE {table_name} SET journal_id = :target_id WHERE journal_id = :source_id"
            ),
            {"target_id": target_id, "source_id": source_id},
        )
        changed_fields[f"{table_name}_added"] = True

    async def _merge_existing_type_data(
        self,
        table_name: str,
        target_id: int,
        source_id: int,
        target_row: Any,
        source_row: Any,
        default_survivor: Journal,
        source: Journal,
        overrides: dict[str, Any],
        changed_fields: dict[str, Any],
        transaction: AsyncConnection,
    ) -> None:
        source_dict = source_row._mapping
        target_dict = target_row._mapping
        updates = []
        update_params: dict[str, Any] = {"target_id": target_id}

        type_enum_names = [
            k
            for k, v in _JOURNAL_TYPE_TABLE_MAP.items()
            if v == table_name and k.isupper()
        ]
        type_overrides = {}
        type_data_overrides = overrides.get("type_data") or {}
        for tenum in type_enum_names:
            type_overrides.update(type_data_overrides.get(tenum, {}))

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

            if s_val is not None and (
                t_val is None or (default_survivor is source and t_val != s_val)
            ):
                updates.append(f"{col} = :{col}")
                update_params[col] = s_val

        if table_name == "journal_calendar_info":
            # Compute full merged state for validation
            merged_state = {
                **target_dict,
                **{k: v for k, v in update_params.items() if k != "target_id"},
            }

            if merged_state.get("is_all_day"):
                if merged_state.get("start_time") is not None:
                    if "start_time" not in update_params:
                        updates.append("start_time = :start_time")
                    update_params["start_time"] = None
                if merged_state.get("end_time") is not None:
                    if "end_time" not in update_params:
                        updates.append("end_time = :end_time")
                    update_params["end_time"] = None

        if updates:
            # Deduplicate just in case
            unique_updates = []
            for u in updates:
                if u not in unique_updates:
                    unique_updates.append(u)

            set_clause = ", ".join(unique_updates)
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

    async def _publish_events_and_cleanup(
        self,
        target_id: int,
        source_id: int,
        source: Journal,
        changed_fields: dict[str, Any],
        transaction: AsyncConnection,
    ) -> None:
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

        await self.event_publisher.publish(
            JournalDeleted(
                source_id,
                user_id=source.user_id,
                external_identifiers={},
                transaction=transaction,
            )
        )
