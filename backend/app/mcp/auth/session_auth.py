"""
MCP session-based authentication middleware.

Provides session-based authentication integration for MCP tools,
reusing the existing OAuth session management system.
"""

from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.infrastructure.auth.models import SessionUser

logger = structlog.get_logger()


class SessionAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to validate session-based authentication for MCP requests.

    This middleware integrates with the existing OAuth session system
    to provide authentication for MCP tools. It only applies to MCP
    endpoints and allows other requests to pass through unchanged.
    """

    def __init__(self, app: ASGIApp, disable_auth: bool = False):
        """Initialize middleware with optional auth disabling."""
        super().__init__(app)
        self.disable_auth = disable_auth

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """
        Process request and validate session for MCP endpoints.

        Args:
            request: The incoming HTTP request
            call_next: The next middleware/handler in the chain

        Returns:
            Response from the next handler or 401 if authentication fails
        """
        # Only apply authentication to MCP endpoints
        if not self._is_mcp_request(request):
            return await call_next(request)

        # If authentication is disabled, create a mock user
        if self.disable_auth:
            from app.infrastructure.auth.models import SessionUser

            mock_user = SessionUser(
                id="dev-user",
                email="dev@example.com",
                name="Development User",
                provider="development",
            )
            request.state.user = mock_user
            logger.debug(
                "MCP: Authentication disabled - using mock user",
                path=request.url.path,
            )
            return await call_next(request)

        # Validate session
        user = self._get_session_user(request)
        if user is None:
            logger.warning(
                "MCP: Unauthorized request - no valid session", path=request.url.path
            )
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Unauthorized",
                    "message": "Valid session required for MCP access",
                },
            )

        # Add user to request state for tools to access
        request.state.user = user

        logger.debug(
            "MCP: Authenticated request",
            user_id=user.id,
            user_email=user.email,
            path=request.url.path,
        )

        return await call_next(request)

    def _is_mcp_request(self, request: Request) -> bool:
        """
        Check if the request is for an MCP endpoint.

        Args:
            request: The HTTP request to check

        Returns:
            True if this is an MCP request, False otherwise
        """
        return request.url.path.startswith("/mcp-server/")

    def _get_session_user(self, request: Request) -> SessionUser | None:
        """
        Extract and validate user from session.

        Args:
            request: The HTTP request containing session data

        Returns:
            SessionUser if valid session exists, None otherwise
        """
        try:
            # Check if session exists
            if not hasattr(request, "session") or not request.session:
                return None

            # Check if user data exists in session
            user_data = request.session.get("user")
            if not user_data:
                return None

            # Validate required fields
            required_fields = ["id", "email", "name", "provider"]
            if not all(field in user_data for field in required_fields):
                logger.warning(
                    "MCP: Invalid session - missing required fields",
                    available_fields=list(user_data.keys()),
                    required_fields=required_fields,
                )
                return None

            # Create SessionUser from session data
            return SessionUser(
                id=user_data["id"],
                email=user_data["email"],
                name=user_data["name"],
                provider=user_data["provider"],
            )

        except Exception as e:
            logger.error("MCP: Error validating session", error=str(e))
            return None
