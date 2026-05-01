"""SQL implementation of ActivityTemplateRepository."""

from typing import Any

from core_shared.models.journals import ActivityTemplate
from core_shared.models.journals.template_pitch import TemplatePitch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import ActivityTemplateRepository


class SqlActivityTemplateRepository(ActivityTemplateRepository):
    """SQL implementation of ActivityTemplateRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_entity(
        self, row: Any, pitches: list[TemplatePitch] | None = None
    ) -> ActivityTemplate:
        """Convert a database row to an ActivityTemplate entity."""
        return ActivityTemplate(
            id=str(row.id),
            user_id=row.user_id,
            name=row.name,
            template_type=row.template_type,
            region=row.region,
            description=row.description,
            french_grade=row.french_grade,
            canyon_type=row.canyon_type,
            water_gauge_name=row.water_gauge_name,
            is_vertical=row.is_vertical,
            is_horizontal=row.is_horizontal,
            climbing_type=row.climbing_type,
            grade=row.grade,
            length=row.length,
            pitches=pitches or [],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _pitch_row_to_entity(self, row: Any) -> TemplatePitch:
        """Convert a database row to a TemplatePitch entity."""
        return TemplatePitch(
            id=row.id,
            template_id=str(row.template_id),
            pitch_number=row.pitch_number,
            height=row.height,
            anchor_location=row.anchor_location,
            anchor_type=row.anchor_type,
            did_rescue=row.did_rescue,
            did_setup=row.did_setup,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def save(self, template: ActivityTemplate) -> ActivityTemplate:
        """
        Save an activity template (insert or update) using atomic UPSERT.

        Uses ON CONFLICT on id to update an existing template or insert a new one.
        Pitches are managed via delete-reinsert pattern to handle additions,
        removals, and reordering atomically.

        Args:
            template: The activity template to save

        Returns:
            The saved template with updated fields (id, timestamps, pitches)

        Raises:
            RuntimeError: If not called within an active database transaction.
        """
        if not self.conn.in_transaction():
            raise RuntimeError(
                "ActivityTemplateRepository.save() must be called within an active transaction"
            )

        query = text(
            """
            INSERT INTO activity_templates (
                id, user_id, name, template_type, region, description,
                french_grade, canyon_type, water_gauge_name,
                is_vertical, is_horizontal,
                climbing_type, grade, length
            )
            VALUES (
                :id, :user_id, :name, :template_type, :region, :description,
                :french_grade, :canyon_type, :water_gauge_name,
                :is_vertical, :is_horizontal,
                :climbing_type, :grade, :length
            )
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                template_type = EXCLUDED.template_type,
                region = EXCLUDED.region,
                description = EXCLUDED.description,
                french_grade = EXCLUDED.french_grade,
                canyon_type = EXCLUDED.canyon_type,
                water_gauge_name = EXCLUDED.water_gauge_name,
                is_vertical = EXCLUDED.is_vertical,
                is_horizontal = EXCLUDED.is_horizontal,
                climbing_type = EXCLUDED.climbing_type,
                grade = EXCLUDED.grade,
                length = EXCLUDED.length,
                updated_at = now()
            WHERE activity_templates.user_id = EXCLUDED.user_id
            RETURNING id, user_id, name, template_type, region, description,
                      french_grade, canyon_type, water_gauge_name,
                      is_vertical, is_horizontal,
                      climbing_type, grade, length,
                      created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "id": template.id,
                "user_id": template.user_id,
                "name": template.name,
                "template_type": template.template_type,
                "region": template.region,
                "description": template.description,
                "french_grade": template.french_grade,
                "canyon_type": template.canyon_type,
                "water_gauge_name": template.water_gauge_name,
                "is_vertical": template.is_vertical,
                "is_horizontal": template.is_horizontal,
                "climbing_type": template.climbing_type,
                "grade": template.grade,
                "length": template.length,
            },
        )
        saved_row = result.fetchone()
        if saved_row is None:
            # If no row is returned, the UPSERT hit a conflict and the WHERE clause failed
            raise PermissionError("Cannot update template belonging to another user.")

        template_id = str(saved_row.id)

        # Delete-reinsert pitches for this template
        await self.conn.execute(
            text("DELETE FROM template_pitches WHERE template_id = :template_id"),
            {"template_id": template_id},
        )

        saved_pitches: list[TemplatePitch] = []
        for pitch in template.pitches:
            pitch_query = text(
                """
                INSERT INTO template_pitches (
                    template_id, pitch_number, height,
                    anchor_location, anchor_type, did_rescue, did_setup
                )
                VALUES (
                    :template_id, :pitch_number, :height,
                    :anchor_location, :anchor_type, :did_rescue, :did_setup
                )
                RETURNING id, template_id, pitch_number, height,
                          anchor_location, anchor_type, did_rescue, did_setup,
                          created_at, updated_at
                """
            )
            pitch_result = await self.conn.execute(
                pitch_query,
                {
                    "template_id": template_id,
                    "pitch_number": pitch.pitch_number,
                    "height": pitch.height,
                    "anchor_location": pitch.anchor_location,
                    "anchor_type": pitch.anchor_type,
                    "did_rescue": pitch.did_rescue,
                    "did_setup": pitch.did_setup,
                },
            )
            pitch_row = pitch_result.fetchone()
            saved_pitches.append(self._pitch_row_to_entity(pitch_row))

        return self._row_to_entity(saved_row, saved_pitches)

    async def find_by_id(self, template_id: str) -> ActivityTemplate | None:
        """Find an activity template by ID, including its pitches."""
        query = text(
            """
            SELECT id, user_id, name, template_type, region, description,
                   french_grade, canyon_type, water_gauge_name,
                   is_vertical, is_horizontal,
                   climbing_type, grade, length,
                   created_at, updated_at
            FROM activity_templates
            WHERE id = :template_id
            """
        )
        result = await self.conn.execute(query, {"template_id": template_id})
        row = result.fetchone()
        if row is None:
            return None

        pitches = await self._find_pitches_by_template_id(template_id)
        return self._row_to_entity(row, pitches)

    async def find_by_user(
        self, user_id: str, template_type: str | None = None
    ) -> list[ActivityTemplate]:
        """Find all templates for a user, optionally filtered by type."""
        if template_type:
            query = text(
                """
                SELECT id, user_id, name, template_type, region, description,
                       french_grade, canyon_type, water_gauge_name,
                       is_vertical, is_horizontal,
                       climbing_type, grade, length,
                       created_at, updated_at
                FROM activity_templates
                WHERE user_id = :user_id AND template_type = :template_type
                ORDER BY name ASC
                """
            )
            result = await self.conn.execute(
                query, {"user_id": user_id, "template_type": template_type}
            )
        else:
            query = text(
                """
                SELECT id, user_id, name, template_type, region, description,
                       french_grade, canyon_type, water_gauge_name,
                       is_vertical, is_horizontal,
                       climbing_type, grade, length,
                       created_at, updated_at
                FROM activity_templates
                WHERE user_id = :user_id
                ORDER BY name ASC
                """
            )
            result = await self.conn.execute(query, {"user_id": user_id})

        rows = result.fetchall()
        templates = []
        for row in rows:
            pitches = await self._find_pitches_by_template_id(str(row.id))
            templates.append(self._row_to_entity(row, pitches))
        return templates

    async def search_by_name(
        self, user_id: str, query: str, template_type: str | None = None
    ) -> list[ActivityTemplate]:
        """Search templates by name using case-insensitive partial matching."""
        search_pattern = f"%{query}%"
        if template_type:
            sql = text(
                """
                SELECT id, user_id, name, template_type, region, description,
                       french_grade, canyon_type, water_gauge_name,
                       is_vertical, is_horizontal,
                       climbing_type, grade, length,
                       created_at, updated_at
                FROM activity_templates
                WHERE user_id = :user_id
                  AND name ILIKE :search_pattern
                  AND template_type = :template_type
                ORDER BY name ASC
                """
            )
            result = await self.conn.execute(
                sql,
                {
                    "user_id": user_id,
                    "search_pattern": search_pattern,
                    "template_type": template_type,
                },
            )
        else:
            sql = text(
                """
                SELECT id, user_id, name, template_type, region, description,
                       french_grade, canyon_type, water_gauge_name,
                       is_vertical, is_horizontal,
                       climbing_type, grade, length,
                       created_at, updated_at
                FROM activity_templates
                WHERE user_id = :user_id AND name ILIKE :search_pattern
                ORDER BY name ASC
                """
            )
            result = await self.conn.execute(
                sql,
                {"user_id": user_id, "search_pattern": search_pattern},
            )

        rows = result.fetchall()
        templates = []
        for row in rows:
            pitches = await self._find_pitches_by_template_id(str(row.id))
            templates.append(self._row_to_entity(row, pitches))
        return templates

    async def delete(self, template_id: str) -> None:
        """Delete an activity template by ID (pitches cascade-deleted)."""
        query = text("DELETE FROM activity_templates WHERE id = :template_id")
        await self.conn.execute(query, {"template_id": template_id})

    async def _find_pitches_by_template_id(
        self, template_id: str
    ) -> list[TemplatePitch]:
        """Find all pitches for a template, ordered by pitch_number."""
        query = text(
            """
            SELECT id, template_id, pitch_number, height,
                   anchor_location, anchor_type, did_rescue, did_setup,
                   created_at, updated_at
            FROM template_pitches
            WHERE template_id = :template_id
            ORDER BY pitch_number
            """
        )
        result = await self.conn.execute(query, {"template_id": template_id})
        return [self._pitch_row_to_entity(row) for row in result.fetchall()]
