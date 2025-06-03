"""
Global error handlers for mapping domain exceptions to JSON API error responses.

Provides a centralized way to handle domain exceptions and convert them to
appropriate HTTP responses following the JSON API specification.
"""

import uuid
from typing import Any

import structlog
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.common.schemas import JsonApiError, JsonApiErrorResponse
from app.core.contacts.models.exceptions import (
    ContactDomainError,
    ContactNotFoundError,
    ContactValidationError,
    DuplicateEmailError,
    PrimaryAddressConflictError,
    PrimaryMethodConflictError,
    TagNotFoundError,
    TooManyTagsError,
)
from app.core.exceptions import DomainError

logger = structlog.get_logger()


def create_json_api_error(
    status: str,
    title: str,
    detail: str | None = None,
    code: str | None = None,
    source: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> JsonApiError:
    """Create a JSON API error object."""
    return JsonApiError(
        id=str(uuid.uuid4()),
        status=status,
        code=code,
        title=title,
        detail=detail,
        source=source,
        meta=meta,
    )


def domain_exception_to_json_api_error(exception: DomainError) -> JsonApiError:
    """Convert a domain exception to a JSON API error."""
    error_id = str(uuid.uuid4())
    status = str(exception.status_code)

    # Map specific exception types to appropriate error details
    if isinstance(exception, ContactNotFoundError):
        return JsonApiError(
            id=error_id,
            status=status,
            code="CONTACT_NOT_FOUND",
            title="Contact Not Found",
            detail=f"Contact with ID {exception.contact_id} does not exist",
            source={"parameter": "id"},
            meta={"contact_id": exception.contact_id},
        )

    elif isinstance(exception, TagNotFoundError):
        return JsonApiError(
            id=error_id,
            status=status,
            code="TAG_NOT_FOUND",
            title="Tag Not Found",
            detail=f"Tag with ID {exception.tag_id} does not exist",
            source={"parameter": "tag_id"},
            meta={"tag_id": exception.tag_id},
        )

    elif isinstance(exception, DuplicateEmailError):
        return JsonApiError(
            id=error_id,
            status=status,
            code="DUPLICATE_EMAIL",
            title="Email Already Exists",
            detail=f"Email '{exception.email}' is already associated with another contact",
            source={"pointer": "/data/attributes/methods"},
            meta={"email": exception.email, "existing_contact_id": exception.existing_contact_id},
        )

    elif isinstance(exception, ContactValidationError):
        return JsonApiError(
            id=error_id,
            status=status,
            code="VALIDATION_ERROR",
            title="Contact Validation Failed",
            detail=f"Validation failed for field '{exception.field}': {exception.message}",
            source={"pointer": f"/data/attributes/{exception.field}"},
            meta={"field": exception.field},
        )

    elif isinstance(exception, PrimaryMethodConflictError):
        return JsonApiError(
            id=error_id,
            status=status,
            code="PRIMARY_METHOD_CONFLICT",
            title="Primary Method Conflict",
            detail=f"Contact already has a primary {exception.method_type} method",
            source={"pointer": "/data/attributes/methods"},
            meta={"contact_id": exception.contact_id, "method_type": exception.method_type},
        )

    elif isinstance(exception, PrimaryAddressConflictError):
        return JsonApiError(
            id=error_id,
            status=status,
            code="PRIMARY_ADDRESS_CONFLICT",
            title="Primary Address Conflict",
            detail="Contact already has a primary address",
            source={"pointer": "/data/attributes/addresses"},
            meta={"contact_id": exception.contact_id},
        )

    elif isinstance(exception, TooManyTagsError):
        return JsonApiError(
            id=error_id,
            status=status,
            code="TOO_MANY_TAGS",
            title="Too Many Tags",
            detail=f"Contact has {exception.current_count} tags. Maximum allowed is 25",
            source={"pointer": "/data/relationships/tags"},
            meta={"contact_id": exception.contact_id, "current_count": exception.current_count, "max_tags": 25},
        )

    elif isinstance(exception, ContactDomainError):
        # Generic contact domain error
        return JsonApiError(
            id=error_id,
            status=status,
            code="CONTACT_DOMAIN_ERROR",
            title="Contact Domain Error",
            detail=exception.message,
        )

    else:
        # Generic domain error
        return JsonApiError(
            id=error_id,
            status=status,
            code="DOMAIN_ERROR",
            title="Domain Error",
            detail=exception.message,
        )


async def domain_exception_handler(request: Request, exc: DomainError) -> JSONResponse:
    """Handle domain exceptions and return JSON API error responses."""
    logger.warning(
        "Domain exception occurred",
        exception_type=type(exc).__name__,
        message=exc.message,
        status_code=exc.status_code,
        path=request.url.path,
    )

    error = domain_exception_to_json_api_error(exc)
    error_response = JsonApiErrorResponse(errors=[error])

    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump(exclude_none=True),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle HTTP exceptions and return JSON API error responses."""
    logger.warning(
        "HTTP exception occurred",
        status_code=exc.status_code,
        detail=exc.detail,
        path=request.url.path,
    )

    error = create_json_api_error(
        status=str(exc.status_code),
        title="HTTP Error",
        detail=exc.detail,
        code="HTTP_ERROR",
    )
    error_response = JsonApiErrorResponse(errors=[error])

    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump(exclude_none=True),
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle validation exceptions and return JSON API error responses."""
    logger.error(
        "Validation exception occurred",
        exception_type=type(exc).__name__,
        message=str(exc),
        path=request.url.path,
    )

    error = create_json_api_error(
        status="422",
        title="Validation Error",
        detail=str(exc),
        code="VALIDATION_ERROR",
    )
    error_response = JsonApiErrorResponse(errors=[error])

    return JSONResponse(
        status_code=422,
        content=error_response.model_dump(exclude_none=True),
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle generic exceptions and return JSON API error responses."""
    logger.error(
        "Unexpected exception occurred",
        exception_type=type(exc).__name__,
        message=str(exc),
        path=request.url.path,
        exc_info=True,
    )

    error = create_json_api_error(
        status="500",
        title="Internal Server Error",
        detail="An unexpected error occurred",
        code="INTERNAL_ERROR",
    )
    error_response = JsonApiErrorResponse(errors=[error])

    return JSONResponse(
        status_code=500,
        content=error_response.model_dump(exclude_none=True),
    )


def register_error_handlers(app: Any) -> None:
    """Register all error handlers with the FastAPI app."""
    app.add_exception_handler(DomainError, domain_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    # Note: Pydantic validation errors would be handled by validation_exception_handler
    # but we'll let FastAPI handle them by default for now
    app.add_exception_handler(Exception, generic_exception_handler)
