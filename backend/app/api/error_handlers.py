"""
Global error handlers for FastAPI application.

Provides centralized error handling that converts domain exceptions
to JSON API compliant error responses.
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog
from core_shared.exceptions import DomainError
from core_shared.models.contacts.exceptions import (
    ContactDomainError,
    ContactValidationError,
)
from core_shared.models.journals import (
    CalendarInfoValidationError,
    CalendarNotFoundError,
    CalendarValidationError,
    GPXParsingError,
    JournalCycleError,
    JournalDomainError,
    JournalHasAnchoredTasksError,
    JournalMaxDepthExceededError,
    JournalNotFoundError,
    JournalTagNotFoundError,
    JournalTypeDependencyError,
    JournalValidationError,
    MoodDataValidationError,
    PlanDataValidationError,
    PlanDocumentValidationError,
    RouteInUseError,
    RouteNotFoundError,
    RouteValidationError,
    TravelAccommodationValidationError,
    TravelDataValidationError,
    TravelFlightValidationError,
    TravelTransportationValidationError,
)
from core_shared.models.tasks import (
    TaskAnchorJournalNotFoundError,
    TaskDueJournalNotFutureError,
    TaskNotFoundError,
    TaskReopenNotAcknowledgedError,
    TaskStatusTransitionError,
    TaskValidationError,
)
from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from app.api.common.schemas import (
    JsonApiError,
    JsonApiErrorResponse,
    JsonApiErrorSource,
)
from app.core.contacts.models.exceptions import (
    ContactMergeConflictError,
    ContactNotFoundError,
    CustomDateTypeInUseError,
    CustomDateTypeNotFoundError,
    DuplicateBirthdayError,
    DuplicateCustomDateTypeNameError,
    DuplicateEmailError,
    DuplicateTagNameError,
    ImportantDateNotFoundError,
    InvalidAddressError,
    InvalidCountryCodeError,
    InvalidEmailError,
    InvalidPhoneNumberError,
    InvalidTagNameError,
    PrimaryAddressConflictError,
    PrimaryMethodConflictError,
    TagNotFoundError,
    TooManyTagsError,
)
from app.core.search.exceptions import SearchDomainError
from app.infrastructure.auth.exceptions import (
    AuthenticationError,
    OAuthError,
    UnauthorizedError,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

# Type alias for exception handlers
ExceptionHandler = Callable[[Request, Exception], Awaitable[Response | JSONResponse]]

logger = structlog.get_logger()


def create_validation_error_response(
    validation_error: ValidationError | RequestValidationError,
) -> JsonApiErrorResponse:
    """Create JSON API error response from Pydantic validation error."""
    errors = []

    for error in validation_error.errors():
        # Build JSON pointer for the error location
        pointer_parts = []
        for loc_part in error["loc"]:
            if isinstance(loc_part, str):
                pointer_parts.append(loc_part)
            elif isinstance(loc_part, int):
                pointer_parts.append(str(loc_part))

        pointer = "/" + "/".join(pointer_parts) if pointer_parts else None

        source = JsonApiErrorSource(pointer=pointer) if pointer else None

        api_error = JsonApiError(
            status="400",
            code="VALIDATION_ERROR",
            title="Validation Error",
            detail=error["msg"],
            source=source,
        )
        errors.append(api_error)

    return JsonApiErrorResponse(errors=errors)


def create_domain_error_response(domain_error: DomainError) -> JsonApiErrorResponse:
    """Create JSON API error response from domain error."""
    error_code_map = {
        # Contact errors
        ContactNotFoundError: "CONTACT_NOT_FOUND",
        ContactMergeConflictError: "CONTACT_MERGE_CONFLICT",
        TagNotFoundError: "TAG_NOT_FOUND",
        DuplicateEmailError: "DUPLICATE_EMAIL",
        DuplicateTagNameError: "DUPLICATE_TAG_NAME",
        ContactValidationError: "CONTACT_VALIDATION_ERROR",
        InvalidEmailError: "INVALID_EMAIL",
        InvalidPhoneNumberError: "INVALID_PHONE_NUMBER",
        InvalidAddressError: "INVALID_ADDRESS",
        InvalidCountryCodeError: "INVALID_COUNTRY_CODE",
        InvalidTagNameError: "INVALID_TAG_NAME",
        TooManyTagsError: "TOO_MANY_TAGS",
        PrimaryMethodConflictError: "PRIMARY_METHOD_CONFLICT",
        PrimaryAddressConflictError: "PRIMARY_ADDRESS_CONFLICT",
        CustomDateTypeNotFoundError: "CUSTOM_DATE_TYPE_NOT_FOUND",
        ImportantDateNotFoundError: "IMPORTANT_DATE_NOT_FOUND",
        DuplicateCustomDateTypeNameError: "DUPLICATE_CUSTOM_DATE_TYPE_NAME",
        CustomDateTypeInUseError: "CUSTOM_DATE_TYPE_IN_USE",
        DuplicateBirthdayError: "DUPLICATE_BIRTHDAY",
        # Journal errors
        JournalNotFoundError: "JOURNAL_NOT_FOUND",
        JournalTagNotFoundError: "JOURNAL_TAG_NOT_FOUND",
        JournalValidationError: "JOURNAL_VALIDATION_ERROR",
        JournalCycleError: "JOURNAL_CYCLE_ERROR",
        JournalHasAnchoredTasksError: "JOURNAL_HAS_ANCHORED_TASKS",
        JournalMaxDepthExceededError: "JOURNAL_MAX_DEPTH_EXCEEDED",
        JournalTypeDependencyError: "JOURNAL_TYPE_DEPENDENCY_ERROR",
        # Task errors
        TaskNotFoundError: "TASK_NOT_FOUND",
        TaskValidationError: "TASK_VALIDATION_ERROR",
        TaskAnchorJournalNotFoundError: "TASK_ANCHOR_JOURNAL_NOT_FOUND",
        TaskDueJournalNotFutureError: "TASK_DUE_JOURNAL_NOT_FUTURE",
        TaskStatusTransitionError: "TASK_STATUS_TRANSITION_REFUSED",
        # Its own code rather than the generic fallback, because the surface has to
        # be able to tell it apart to offer *"reopen it anyway"*. Carried forward
        # from the phase that introduced the error with no endpoint able to raise
        # it: until the retarget route existed this rendered as ``DOMAIN_ERROR``,
        # which is correct for an unreachable error and useless to a reachable one.
        TaskReopenNotAcknowledgedError: "TASK_REOPEN_NOT_ACKNOWLEDGED",
        # Calendar errors
        CalendarNotFoundError: "CALENDAR_NOT_FOUND",
        CalendarValidationError: "CALENDAR_VALIDATION_ERROR",
        CalendarInfoValidationError: "CALENDAR_INFO_VALIDATION_ERROR",
        # Type-specific validation errors
        MoodDataValidationError: "MOOD_DATA_VALIDATION_ERROR",
        PlanDataValidationError: "PLAN_DATA_VALIDATION_ERROR",
        PlanDocumentValidationError: "PLAN_DOCUMENT_VALIDATION_ERROR",
        TravelDataValidationError: "TRAVEL_DATA_VALIDATION_ERROR",
        TravelFlightValidationError: "TRAVEL_FLIGHT_VALIDATION_ERROR",
        TravelAccommodationValidationError: "TRAVEL_ACCOMMODATION_VALIDATION_ERROR",
        TravelTransportationValidationError: "TRAVEL_TRANSPORTATION_VALIDATION_ERROR",
        # Route errors
        RouteNotFoundError: "ROUTE_NOT_FOUND",
        RouteValidationError: "ROUTE_VALIDATION_ERROR",
        RouteInUseError: "ROUTE_IN_USE",
        # GPX errors
        GPXParsingError: "GPX_PARSING_ERROR",
    }

    error_code = error_code_map.get(type(domain_error), "DOMAIN_ERROR")

    api_error = JsonApiError(
        status=str(domain_error.status_code),
        code=error_code,
        title=type(domain_error)
        .__name__.replace("Error", " Error")
        .replace("_", " ")
        .title(),
        detail=domain_error.message,
        # Machine-readable detail for the few refusals whose prose is not enough
        # to act on — see ``DomainError.error_meta``. Every other error returns
        # ``None`` here, and the response is dumped with ``exclude_none=True``,
        # so their bodies are byte-for-byte what they were.
        meta=domain_error.error_meta(),
    )

    return JsonApiErrorResponse(errors=[api_error])


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    """Handle domain errors and return JSON API compliant responses."""
    logger.warning(
        "Domain error occurred",
        error_type=type(exc).__name__,
        error_message=exc.message,
        status_code=exc.status_code,
        path=request.url.path,
    )

    error_response = create_domain_error_response(exc)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump(exclude_none=True),
    )


async def contact_domain_error_handler(
    request: Request, exc: ContactDomainError
) -> JSONResponse:
    """Handle contact domain errors specifically."""
    return await domain_error_handler(request, exc)


async def search_domain_error_handler(
    request: Request, exc: SearchDomainError
) -> JSONResponse:
    """Handle search domain errors specifically."""
    return await domain_error_handler(request, exc)


async def journal_domain_error_handler(
    request: Request, exc: JournalDomainError
) -> JSONResponse:
    """Handle journal domain errors specifically."""
    return await domain_error_handler(request, exc)


async def authentication_error_handler(
    request: Request, exc: AuthenticationError
) -> JSONResponse:
    """Handle authentication errors."""
    logger.warning("Authentication error", error=str(exc), path=request.url.path)

    error = JsonApiError(
        status="401",
        code="AUTHENTICATION_ERROR",
        title="Authentication Error",
        detail=str(exc),
    )

    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content=JsonApiErrorResponse(errors=[error]).model_dump(),
        headers={"WWW-Authenticate": "Bearer"},
    )


async def oauth_error_handler(request: Request, exc: OAuthError) -> JSONResponse:
    """Handle OAuth errors."""
    logger.warning(
        "OAuth error", error=str(exc), provider=exc.provider, path=request.url.path
    )

    error = JsonApiError(
        status="400",
        code="OAUTH_ERROR",
        title="OAuth Error",
        detail=str(exc),
        meta={"provider": exc.provider},
    )

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=JsonApiErrorResponse(errors=[error]).model_dump(),
    )


async def unauthorized_error_handler(
    request: Request, exc: UnauthorizedError
) -> JSONResponse:
    """Handle unauthorized access errors."""
    logger.warning("Unauthorized access", error=str(exc), path=request.url.path)

    error = JsonApiError(
        status="403",
        code="UNAUTHORIZED",
        title="Unauthorized",
        detail=str(exc),
    )

    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content=JsonApiErrorResponse(errors=[error]).model_dump(),
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors."""
    logger.warning(
        "Validation error occurred",
        errors=exc.errors(),
        path=request.url.path,
    )

    error_response = create_validation_error_response(exc)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=error_response.model_dump(exclude_none=True),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle FastAPI HTTP exceptions."""
    logger.warning(
        "HTTP exception occurred",
        status_code=exc.status_code,
        detail=exc.detail,
        path=request.url.path,
    )

    api_error = JsonApiError(
        status=str(exc.status_code),
        code="HTTP_ERROR",
        title="HTTP Error",
        detail=str(exc.detail),
    )

    error_response = JsonApiErrorResponse(errors=[api_error])
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump(exclude_none=True),
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions."""
    logger.error(
        "Unexpected error occurred",
        error_type=type(exc).__name__,
        error_message=str(exc),
        path=request.url.path,
        exc_info=True,
    )

    api_error = JsonApiError(
        status="500",
        code="INTERNAL_ERROR",
        title="Internal Server Error",
        detail="An unexpected error occurred. Please try again later.",
    )

    error_response = JsonApiErrorResponse(errors=[api_error])
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response.model_dump(exclude_none=True),
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register all error handlers with the FastAPI application."""
    # Cast handlers to the expected type
    contact_handler: ExceptionHandler = contact_domain_error_handler  # type: ignore[assignment]
    search_handler: ExceptionHandler = search_domain_error_handler  # type: ignore[assignment]
    journal_handler: ExceptionHandler = journal_domain_error_handler  # type: ignore[assignment]
    domain_handler: ExceptionHandler = domain_error_handler  # type: ignore[assignment]
    validation_handler: ExceptionHandler = validation_error_handler  # type: ignore[assignment]
    http_handler: ExceptionHandler = http_exception_handler  # type: ignore[assignment]
    generic_handler: ExceptionHandler = generic_exception_handler
    auth_handler: ExceptionHandler = authentication_error_handler  # type: ignore[assignment]
    oauth_handler: ExceptionHandler = oauth_error_handler  # type: ignore[assignment]
    unauthorized_handler: ExceptionHandler = unauthorized_error_handler  # type: ignore[assignment]

    # Authentication error handlers (most specific first)
    app.add_exception_handler(OAuthError, oauth_handler)
    app.add_exception_handler(UnauthorizedError, unauthorized_handler)
    app.add_exception_handler(AuthenticationError, auth_handler)

    # Domain error handlers (most specific first)
    app.add_exception_handler(ContactDomainError, contact_handler)
    app.add_exception_handler(SearchDomainError, search_handler)
    app.add_exception_handler(JournalDomainError, journal_handler)
    app.add_exception_handler(DomainError, domain_handler)

    # Validation error handlers
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(ValidationError, validation_handler)

    # HTTP exception handler
    app.add_exception_handler(HTTPException, http_handler)

    # Generic exception handler (catch-all)
    app.add_exception_handler(Exception, generic_handler)
