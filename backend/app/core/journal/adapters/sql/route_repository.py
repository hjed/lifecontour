"""SQL implementation of RouteRepository using SQLAlchemy Core."""

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
            SELECT id, journal_id, name, description, gpx_data, created_at, updated_at
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
            journal_id=row.journal_id,
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
                INSERT INTO routes (journal_id, name, description, gpx_data)
                VALUES (:journal_id, :name, :description, :gpx_data)
                RETURNING id, created_at, updated_at
            """
            )
            result = await self.conn.execute(
                query,
                {
                    "journal_id": route.journal_id,
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
                SET journal_id = :journal_id,
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
                    "journal_id": route.journal_id,
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

    async def find_by_journal_id(self, journal_id: int) -> list[Route]:
        """Get all routes associated with a specific journal."""
        query = text(
            """
            SELECT id, journal_id, name, description, gpx_data, created_at, updated_at
            FROM routes
            WHERE journal_id = :journal_id
            ORDER BY created_at ASC
        """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        return [
            Route(
                id=row.id,
                journal_id=row.journal_id,
                name=row.name,
                description=row.description,
                gpx_data=row.gpx_data,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in result.fetchall()
        ]
