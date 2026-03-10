"""SQL implementation of RouteRepository using SQLAlchemy Core."""

from typing import Any
from uuid import UUID

from core_shared.models.route import Route
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import RouteRepository


class SqlRouteRepository(RouteRepository):
    """SQL implementation of RouteRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize with database connection."""
        self.conn = connection

    async def find_by_id(self, route_id: UUID) -> Route | None:
        """Find a route by ID."""
        query = text(
            """
            SELECT id, user_id, name, description, gpx_data, created_at, updated_at
            FROM routes
            WHERE id = :route_id
        """
        )
        result = await self.conn.execute(query, {"route_id": route_id})
        row = result.fetchone()

        if not row:
            return None

        return Route(
            id=row.id,
            user_id=row.user_id,
            name=row.name,
            description=row.description,
            gpx_data=row.gpx_data,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def save(self, route: Route) -> Route:
        """Save a route (insert or update)."""
        if route.id is None:
            # Insert new route
            query = text(
                """
                INSERT INTO routes (user_id, name, description, gpx_data)
                VALUES (:user_id, :name, :description, :gpx_data)
                RETURNING id, created_at, updated_at
            """
            )
            result = await self.conn.execute(
                query,
                {
                    "user_id": route.user_id,
                    "name": route.name,
                    "description": route.description,
                    "gpx_data": route.gpx_data,
                },
            )
            row = result.fetchone()
            if row is not None:
                route.id = row.id
                route.created_at = row.created_at
                route.updated_at = row.updated_at
        else:
            # Update existing route
            query = text(
                """
                UPDATE routes
                SET user_id = :user_id,
                    name = :name,
                    description = :description,
                    gpx_data = :gpx_data,
                    updated_at = clock_timestamp()
                WHERE id = :id
                RETURNING updated_at
            """
            )
            result = await self.conn.execute(
                query,
                {
                    "id": route.id,
                    "user_id": route.user_id,
                    "name": route.name,
                    "description": route.description,
                    "gpx_data": route.gpx_data,
                },
            )
            row = result.fetchone()
            if row is not None:
                route.updated_at = row.updated_at

        return route

    async def delete(self, route_id: UUID) -> None:
        """Delete a route by ID."""
        query = text("DELETE FROM routes WHERE id = :route_id")
        await self.conn.execute(query, {"route_id": route_id})
        # Note: We don't raise an error if the route doesn't exist
        # This is consistent with the integration test expectations

    def _build_route_filters(
        self, user_id: str, name: str | None = None
    ) -> tuple[list[str], dict[str, Any]]:
        """Build shared WHERE clauses and parameters for route listing queries."""
        where_clauses = ["user_id = :user_id"]
        params: dict[str, Any] = {"user_id": user_id}

        if name:
            where_clauses.append("name ILIKE :name_pattern")
            params["name_pattern"] = f"%{name}%"

        return where_clauses, params

    async def get_all(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
        name: str | None = None,
    ) -> list[Route]:
        """Get all routes for a user with pagination."""
        where_clauses, params = self._build_route_filters(user_id, name)
        query = text(
            """
            SELECT id, user_id, name, description, gpx_data, created_at, updated_at
            FROM routes
            WHERE """
            + " AND ".join(where_clauses)
            + """
            ORDER BY name ASC, created_at DESC
            LIMIT :limit OFFSET :offset
        """
        )
        params["limit"] = limit
        params["offset"] = offset
        result = await self.conn.execute(query, params)
        return [
            Route(
                id=row.id,
                user_id=row.user_id,
                name=row.name,
                description=row.description,
                gpx_data=row.gpx_data,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in result.fetchall()
        ]

    async def get_count(self, user_id: str, name: str | None = None) -> int:
        """Get total count of routes for a user."""
        where_clauses, params = self._build_route_filters(user_id, name)
        query = text(
            """
            SELECT COUNT(*)
            FROM routes
            WHERE """
            + " AND ".join(where_clauses)
        )
        result = await self.conn.execute(query, params)
        row = result.fetchone()
        return row[0] if row else 0

    async def check_usage_in_journals(self, route_id: UUID) -> bool:
        """
        Check if a route is referenced by any journal entries.

        Routes are referenced by activity-specific data tables (journal_bushwalking_data,
        journal_kayaking_data, journal_climbing_data, journal_skiing_data, journal_jogging_data),
        NOT by the journals table itself.

        Note: This will be properly implemented in future iterations when activity-specific
        tables are added. For now, returns False to allow route deletion.

        Returns:
            True if route is in use by any activity-specific journal data, False otherwise
        """
        # TODO: Check activity-specific tables when they are implemented:
        # - journal_bushwalking_data.route_id
        # - journal_kayaking_data.route_id
        # - journal_climbing_data.route_id
        # - journal_skiing_data.route_id
        # - journal_jogging_data.route_id
        # - journal_canyoning_data.route_id
        return False
