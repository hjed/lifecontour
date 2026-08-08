"""Bounds for the identifiers this application's surfaces accept.

Every primary key in this schema is a PostgreSQL ``INTEGER`` — a signed 32-bit
column — but Python's ``int`` is unbounded, so a request naming ``2147483648``
parses cleanly, reaches the repository, and dies in the driver: asyncpg raises
``DataError: value out of int32 range`` while *binding* the parameter, before
the query is ever sent. That is a **500 for what is plainly a bad request**, and
it is unactionable — the caller is told the server broke when the truth is that
no such row could exist.

Bounding the id at the surface turns it back into the 400 the client deserves,
and does so where the constraint actually lives: this is a statement about the
column's width, not about any domain rule, so it belongs in the request schema
rather than in a service.

The lower bound is ``1`` because these are serial columns: zero and negatives
identify nothing. That half was already enforced piecemeal by domain entities;
stating it here means a surface refuses the value instead of a query returning
nothing and being reported as "not found", which reads as though the row might
have existed once.

**Scope, stated honestly:** this module is applied to the tasks surface, which
is where the gap was found. Every other domain's endpoints take bare ``int``
ids and have the same 500 waiting in them. That is a codebase-wide change with
its own review, tracked separately rather than smuggled into a phase that only
ships contact links.
"""

from typing import Annotated

from fastapi import Path
from pydantic import Field

# PostgreSQL ``INTEGER``: signed 32-bit. Every id column in this schema is one.
INT32_MAX = 2_147_483_647

DatabaseId = Annotated[int, Field(ge=1, le=INT32_MAX)]
"""A body or tool parameter naming a row, bounded to what the column can hold."""

DatabaseIdPath = Annotated[int, Path(ge=1, le=INT32_MAX)]
"""The same bound for a path parameter, where FastAPI needs ``Path`` to see it."""
