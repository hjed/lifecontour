"""Service for merging journals."""

from typing import Any

import structlog
from core_shared.models.journals import (
    FitnessMergeMode,
    Journal,
    JournalNotFoundError,
)
from core_shared.models.journals.exceptions import JournalMergeConflictError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.journal.adapters.sql.journal_repository import _JOURNAL_TYPE_TABLE_MAP
from app.core.journal.models.events import (
    JournalDeleted,
    JournalUpdated,
)
from app.core.journal.models.repositories import JournalRepository
from app.core.journal.services.type_data_coercion import coerce_type_data_override
from app.core.tasks.models.repositories import TaskAnchorRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import transactional

logger = structlog.get_logger(__name__)

FITNESS_TABLE = "journal_fitness_data"

STRAVA_SOURCE = "strava"
STRAVA_ACTIVITY_ENTITY_TYPE = "activity"

# Metrics that describe a quantity of activity, so two rows' values add up.
_FITNESS_SUMMED_COLUMNS = (
    "distance",
    "duration",
    "elevation_gain",
    "elevation_loss",
    "calories",
)


class JournalMergeService:
    """Service for handling journal merges in Phase 1."""

    def __init__(
        self,
        journal_repo: JournalRepository,
        event_publisher: OutboxEventPublisher,
        task_anchor_repo: TaskAnchorRepository,
    ):
        self.journal_repo = journal_repo
        self.event_publisher = event_publisher
        self.task_anchor_repo = task_anchor_repo
        # Column types describe the schema, not any one journal, so they are
        # worth keeping for as long as this service lives.
        self._column_type_cache: dict[str, dict[str, str]] = {}

    def has_base_conflicts(self, target: Journal, source: Journal) -> bool:
        """Check whether two journals have conflicting base fields.

        Returns True if title, content, or event_date_range differ between the
        two journals when **both** have non-empty values for those fields.
        This mirrors the conflict detection in the frontend MergeResolutionDialog.
        """
        # Title conflict: both non-empty and different
        if source.title and target.title and source.title != target.title:
            return True

        # Content conflict: both non-empty and different
        if source.content and target.content and source.content != target.content:
            return True

        # Date range conflict: both non-null and different
        if (
            source.event_date_range
            and target.event_date_range
            and source.event_date_range != target.event_date_range
        ):
            return True

        return False

    @transactional
    async def merge_journals(
        self,
        target_id: int,
        source_id: int,
        transaction: AsyncConnection,
        overrides: dict[str, Any] | None = None,
        fitness_merge_mode: FitnessMergeMode = FitnessMergeMode.REPLACE,
    ) -> Journal:
        """
        Merge source_id journal into target_id journal.
        Returns the merged target journal.
        Deletes the source journal.

        ``fitness_merge_mode`` decides what happens when both journals carry
        fitness data. The default treats them as rival descriptions of one
        activity; ``ADDITIVE`` treats them as two parts of one outing, summing
        the metrics and keeping both journals' integration links.
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

        # 0. Re-point task links, before any other write.
        #
        # It has to happen before the source is deleted: a task's two anchors are
        # ON DELETE RESTRICT, so a task left pointing at the source would fail
        # the merge outright, and its intermediate links cascade, so they would
        # be destroyed rather than moved. Merge is deliberately never blocked by
        # a task.
        #
        # It happens *first* because of what it locks. The repository takes
        # ``FOR UPDATE`` on both journals in ascending id order, and every write
        # below — starting with ``journal_repo.save(target)`` — locks a journal
        # row too. Re-pointing later would mean this transaction had already
        # taken the target's lock out of that order, so two merges in opposite
        # directions (A into B, B into A) could hold each other's target and
        # deadlock. Taking both locks up front, in one order, is what makes the
        # ordering claim true rather than merely intended.
        await self.task_anchor_repo.repoint_journal_links(
            source_journal_id=source_id, target_journal_id=target_id
        )

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

        # 7. Re-point integration links in the canonical link store
        await self._repoint_integration_links(
            target_id, source_id, fitness_merge_mode, transaction
        )

        # 8. Type Data Scalable merge
        await self._merge_type_data(
            target_id,
            source_id,
            default_survivor,
            source,
            overrides,
            changed_fields,
            fitness_merge_mode,
            transaction,
        )

        # 9. Resolve related Review Items
        await self._resolve_review_items(
            target_id, source_id, target.user_id, transaction
        )

        # 10. Publish Events & Cleanup Source
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
                    "Merge title conflict resolved",
                    kept=target.title,
                    discarded=default_loser.title,
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
                    "Merge date conflict resolved",
                    kept=str(target.event_date_range),
                    discarded=str(default_loser.event_date_range),
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
        # Both statements cover every relationship_type (PARTICIPANT, INVITEE,
        # MENTION, ABOUT), not just participants.
        #
        # Backfill first: existing target rows keep their own status/role, but pick
        # up the source's values wherever the target left them unset.
        await transaction.execute(
            text("""
                UPDATE journal_contact_relationships target_rels
                SET status = COALESCE(target_rels.status, source_rels.status),
                    role = COALESCE(target_rels.role, source_rels.role)
                FROM journal_contact_relationships source_rels
                WHERE target_rels.journal_id = :target_id
                AND source_rels.journal_id = :source_id
                AND target_rels.contact_id = source_rels.contact_id
                AND target_rels.relationship_type = source_rels.relationship_type
            """),
            {"target_id": target_id, "source_id": source_id},
        )
        # Then carry over the relationships the target does not have at all, status
        # and role included.
        await transaction.execute(
            text("""
                INSERT INTO journal_contact_relationships
                    (journal_id, contact_id, relationship_type, status, role)
                SELECT :target_id, contact_id, relationship_type, status, role
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

    async def _repoint_integration_links(
        self,
        target_id: int,
        source_id: int,
        fitness_merge_mode: FitnessMergeMode,
        transaction: AsyncConnection,
    ) -> None:
        """Move the source's canonical integration links onto the target.

        ``sync_metadata`` has no ``ON DELETE CASCADE``, so without this the
        deleted source leaves link rows pointing at an id that no longer
        resolves. An additive merge keeps a same-service collision as two links
        (both Strava activities stay reachable); a replace merge drops the
        source's, as contact merge does.

        A Strava activity id can also reach a journal without a sync row behind
        it — typed into the fitness editor by hand — so both journals'
        ``journal_fitness_data`` ids are folded in: the target's so a replace
        merge recognises the source's Strava link as the rival it is, the
        source's so an additive merge does not lose it when the source's
        fitness row is deleted further down.
        """
        is_additive = fitness_merge_mode is FitnessMergeMode.ADDITIVE
        sync_metadata_repo = SyncMetadataRepository(transaction)

        target_activity_id = await self._fitness_strava_activity_id(
            target_id, transaction
        )
        source_activity_id = await self._fitness_strava_activity_id(
            source_id, transaction
        )

        collisions = await sync_metadata_repo.repoint_journal_links(
            source_id,
            target_id,
            transaction,
            keep_colliding_source_links=is_additive,
            extra_target_links=(
                {STRAVA_SOURCE: target_activity_id} if target_activity_id else None
            ),
        )

        if (
            is_additive
            and source_activity_id
            and source_activity_id != target_activity_id
        ):
            await sync_metadata_repo.link_journal_if_unlinked(
                target_id,
                STRAVA_SOURCE,
                source_activity_id,
                STRAVA_ACTIVITY_ENTITY_TYPE,
                transaction,
            )

        if collisions:
            logger.info(
                "Merge reconciled same-service integration links",
                target_id=target_id,
                source_id=source_id,
                kept_both=is_additive,
                collisions=[collision.as_dict() for collision in collisions],
            )

    @staticmethod
    async def _fitness_strava_activity_id(
        journal_id: int, transaction: AsyncConnection
    ) -> str | None:
        """The Strava activity named by a journal's fitness row, if any."""
        result = await transaction.execute(
            text(
                f"SELECT strava_activity_id FROM {FITNESS_TABLE} "
                "WHERE journal_id = :journal_id"
            ),
            {"journal_id": journal_id},
        )
        row = result.fetchone()
        if row is None:
            return None
        activity_id: str | None = row.strava_activity_id
        return activity_id

    async def _merge_type_data(
        self,
        target_id: int,
        source_id: int,
        default_survivor: Journal,
        source: Journal,
        overrides: dict[str, Any],
        changed_fields: dict[str, Any],
        fitness_merge_mode: FitnessMergeMode,
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
                    fitness_merge_mode,
                    transaction,
                )

    @staticmethod
    def _combine_fitness_metrics(target_dict: Any, source_dict: Any) -> dict[str, Any]:
        """Combine two fitness rows as two parts of one outing.

        Quantities of activity sum, the peak heart rate is the higher of the
        two, and the average heart rate is weighted by how long each part
        lasted (an even split when either duration is missing, since there is
        nothing to weight by).

        A missing value means "not recorded", never zero: where only one side
        has a number, that number is the answer, and where neither does the
        column is left out entirely so the caller writes nothing.

        Columns absent from the returned mapping — ``strava_activity_id``, the
        timestamps — keep the ordinary merge behaviour. The source's Strava id
        is not lost by that: it carries over as a ``sync_metadata`` link.
        """
        combined: dict[str, Any] = {}

        for col in _FITNESS_SUMMED_COLUMNS:
            values = [
                value
                for value in (target_dict.get(col), source_dict.get(col))
                if value is not None
            ]
            if values:
                combined[col] = sum(values)

        max_heart_rates = [
            value
            for value in (
                target_dict.get("heart_rate_max"),
                source_dict.get("heart_rate_max"),
            )
            if value is not None
        ]
        if max_heart_rates:
            combined["heart_rate_max"] = max(max_heart_rates)

        average = JournalMergeService._combine_average_heart_rate(
            target_dict, source_dict
        )
        if average is not None:
            combined["heart_rate_avg"] = average

        return combined

    @staticmethod
    def _combine_average_heart_rate(target_dict: Any, source_dict: Any) -> int | None:
        """Average two heart rates, weighted by each part's duration."""
        parts = [
            (target_dict.get("heart_rate_avg"), target_dict.get("duration")),
            (source_dict.get("heart_rate_avg"), source_dict.get("duration")),
        ]
        recorded: list[tuple[int, int | None]] = [
            (rate, duration) for rate, duration in parts if rate is not None
        ]

        if not recorded:
            return None
        if len(recorded) == 1:
            return recorded[0][0]

        durations = [duration for _, duration in recorded]
        if (
            any(duration is None for duration in durations)
            or sum(duration or 0 for duration in durations) == 0
        ):
            # Nothing to weight by — a duration was never recorded, or every
            # part is zero-length — so treat the parts as equally long. A
            # recorded zero is a real weight and only lands here when it is the
            # only one, which would otherwise divide by zero.
            weights = [1] * len(recorded)
        else:
            weights = [duration or 0 for duration in durations]

        total_weight = sum(weights)
        weighted_sum = sum(
            rate * weight for (rate, _), weight in zip(recorded, weights, strict=True)
        )
        return round(weighted_sum / total_weight)

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

    async def _column_types(
        self, table_name: str, transaction: AsyncConnection
    ) -> dict[str, str]:
        """Map each column of ``table_name`` to its Postgres data type.

        Cached per merge: a journal has at most one row per type table, so the
        lookup runs once for each table that actually carries overrides.
        """
        cached = self._column_type_cache.get(table_name)
        if cached is not None:
            return cached

        result = await transaction.execute(
            text("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
            """),
            {"table_name": table_name},
        )
        column_types = {row.column_name: row.data_type for row in result.fetchall()}
        self._column_type_cache[table_name] = column_types
        return column_types

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
        fitness_merge_mode: FitnessMergeMode,
        transaction: AsyncConnection,
    ) -> None:
        source_dict = source_row._mapping
        target_dict = target_row._mapping
        updates = []
        update_params: dict[str, Any] = {"target_id": target_id}

        # Both casings of a type key map to the same table ("FITNESS" and
        # "fitness"), and callers legitimately use either: the enum name in
        # hand-written payloads, the lowercase enum value the read API returns
        # and the merge panel echoes back. Accept both rather than dropping
        # half the overrides on the floor.
        type_keys = [k for k, v in _JOURNAL_TYPE_TABLE_MAP.items() if v == table_name]
        type_overrides = {}
        type_data_overrides = overrides.get("type_data") or {}
        for type_key in type_keys:
            type_overrides.update(type_data_overrides.get(type_key, {}))

        # Overrides arrive as JSON, so a clock time is the string '19:30:00'
        # while its column is a TIME. asyncpg encodes each parameter against the
        # column's type and refuses the string, so give every override the type
        # its column takes before it reaches the UPDATE below.
        if type_overrides:
            column_types = await self._column_types(table_name, transaction)
            type_overrides = {
                col: coerce_type_data_override(col, value, column_types.get(col))
                for col, value in type_overrides.items()
            }

        combined = (
            self._combine_fitness_metrics(target_dict, source_dict)
            if table_name == FITNESS_TABLE
            and fitness_merge_mode is FitnessMergeMode.ADDITIVE
            else {}
        )

        for col in source_dict.keys():
            if col in ("id", "journal_id"):
                continue

            if col in type_overrides:
                if type_overrides[col] != target_dict[col]:
                    updates.append(f"{col} = :{col}")
                    update_params[col] = type_overrides[col]
                continue

            if col in combined:
                if combined[col] != target_dict[col]:
                    updates.append(f"{col} = :{col}")
                    update_params[col] = combined[col]
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

    async def _resolve_review_items(
        self,
        target_id: int,
        source_id: int,
        user_id: str,
        transaction: AsyncConnection,
    ) -> None:
        await transaction.execute(
            text("""
                UPDATE journal_review_items
                SET status = 'resolved', updated_at = NOW()
                WHERE status = 'pending'
                  AND user_id = :user_id
                  AND ((source_journal_id = :target_id AND candidate_journal_id = :source_id)
                    OR (source_journal_id = :source_id AND candidate_journal_id = :target_id))
            """),
            {"target_id": target_id, "source_id": source_id, "user_id": user_id},
        )
