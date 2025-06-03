"""
Common JSON API schemas and base models.

These schemas follow the JSON API specification and are used across
all API domains (contacts, tasks, journals, etc.).
"""

from typing import Any

from pydantic import BaseModel


class JsonApiMeta(BaseModel):
    """JSON API meta object for pagination and additional information."""

    total_count: int | None = None
    page_count: int | None = None
    current_page: int | None = None


class JsonApiLinks(BaseModel):
    """JSON API links object for pagination and navigation."""

    self: str | None = None
    first: str | None = None
    last: str | None = None
    prev: str | None = None
    next: str | None = None


class JsonApiError(BaseModel):
    """JSON API error object for structured error responses."""

    id: str | None = None
    status: str
    code: str | None = None
    title: str
    detail: str | None = None
    source: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None


class JsonApiErrorResponse(BaseModel):
    """JSON API error response containing one or more errors."""

    errors: list[JsonApiError]
    meta: JsonApiMeta | None = None
