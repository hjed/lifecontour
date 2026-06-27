"""
Authentication providers for Dishka dependency injection.

Provides authentication-related services and user session management.

Two authentication methods are supported and resolved in order:

1. ``Authorization: Bearer <jwt>`` — an IdP-issued access token, validated
   locally against the IdP's JWKS (for non-browser API clients). May carry
   ``pms:read``/``pms:write``/``pms:admin`` scopes that are enforced per request.
2. Session cookie — established via the interactive OAuth login (browser).

Session and dev users implicitly hold all scopes; scope enforcement only
applies to bearer tokens that carry recognized ``pms:*`` scopes.
"""

from dataclasses import dataclass

import pydantic
import structlog
from dishka import Provider, Scope, provide
from fastapi import HTTPException, Request, status
from fastmcp.server.auth.providers.jwt import JWTVerifier
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.auth.bearer_token import create_jwt_verifier
from app.infrastructure.auth.google_token_service import GoogleTokenService
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.auth.oauth_service import OAuthService
from app.infrastructure.auth.scopes import (
    ApiScope,
    recognized_scopes,
    required_scope_for_method,
    token_satisfies,
)
from app.infrastructure.auth.token_user import session_user_from_claims
from app.infrastructure.config import Settings

logger = structlog.get_logger()

_BEARER_PREFIX = "bearer "


def _dev_user() -> SessionUser:
    """Mock user used when authentication is disabled (development/testing)."""
    return SessionUser(
        id="dev-user",
        email="dev@example.com",
        name="Development User",
        provider="development",
    )


def _bearer_token(request: Request) -> str | None:
    """Extract the bearer token from the Authorization header, if present."""
    header = request.headers.get("Authorization", "")
    if header.lower().startswith(_BEARER_PREFIX):
        return header[len(_BEARER_PREFIX) :].strip() or None
    return None


async def _verify_bearer(
    token: str, verifier: JWTVerifier
) -> tuple[SessionUser, frozenset[str]] | None:
    """Validate a bearer token; return (user, granted scopes) or None if invalid."""
    access = await verifier.verify_token(token)
    if access is None:
        return None
    try:
        user = session_user_from_claims(
            access.claims, access.client_id, provider="oauth-token"
        )
    except ValueError:
        # Verified token carried no usable identity claim — treat as invalid.
        logger.warning("Bearer token has no usable identity claim")
        return None
    return user, frozenset(access.scopes or [])


@dataclass(frozen=True)
class AuthContext:
    """The authenticated user plus their granted API scopes for a request.

    ``scopes`` semantics:
    - ``None`` — the caller holds ALL scopes including admin (session/dev user,
      or any valid bearer token when scope enforcement is disabled).
    - a (possibly empty) ``frozenset`` — the caller holds exactly these
      ``pms:*`` scopes; ``require_admin`` denies unless ``pms:admin`` is present.
      A valid bearer token carrying no recognized ``pms:*`` scope maps to an
      EMPTY set (regular access, but admin denied) — NOT ``None``. Do not
      change this to ``None`` or scope-less tokens would regain admin access.
    """

    user: SessionUser
    scopes: frozenset[str] | None


class AdminAccess:
    """Marker dependency whose resolution asserts admin-level access."""


class AuthProvider(Provider):
    """Provider for authentication-related dependencies."""

    @provide(scope=Scope.APP)
    async def get_jwt_verifier(self, settings: Settings) -> JWTVerifier | None:
        """Build the bearer-token JWT verifier (app-lifetime, JWKS cached).

        Returns None when bearer auth is not configured (no ``oauth_issuer``),
        in which case the API authenticates via session cookies only.
        """
        return await create_jwt_verifier(settings)

    @provide(scope=Scope.REQUEST)
    def get_oauth_service(self, settings: Settings) -> OAuthService:
        """Get OAuth service instance for request scope."""
        return OAuthService(settings)

    @provide(scope=Scope.REQUEST)
    def get_google_token_service(
        self, connection: AsyncConnection, settings: Settings
    ) -> GoogleTokenService:
        """Get Google Token service instance for request scope."""
        return GoogleTokenService(
            connection=connection,
            encryption_key=settings.google_encryption_key,
        )

    @provide(scope=Scope.REQUEST)
    async def get_auth_context(
        self,
        request: Request,
        settings: Settings,
        verifier: JWTVerifier | None,
    ) -> AuthContext:
        """Authenticate the request via bearer token or session cookie.

        Raises HTTP 401 if neither method authenticates, and HTTP 403 if a
        scoped bearer token lacks the scope required for the request method.
        """
        if settings.disable_auth:
            return AuthContext(user=_dev_user(), scopes=None)

        token = _bearer_token(request)
        if token is not None and verifier is not None:
            result = await _verify_bearer(token, verifier)
            if result is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            user, granted = result
            if not settings.oauth_enforce_scopes:
                # Enforcement disabled: any valid token has full access.
                return AuthContext(user=user, scopes=None)

            recognized = recognized_scopes(set(granted))
            if recognized:
                required = required_scope_for_method(request.method)
                if not token_satisfies(recognized, required):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Requires '{required.value}' scope",
                    )
                return AuthContext(user=user, scopes=frozenset(recognized))
            # Valid token carrying no recognized pms:* scopes: accept for regular
            # (read/write) access but never admin — admin requires an explicit
            # pms:admin scope. Represented as an empty (non-None) scope set so
            # require_admin denies it.
            return AuthContext(user=user, scopes=frozenset())

        return AuthContext(user=_session_user(request), scopes=None)

    @provide(scope=Scope.REQUEST)
    def get_current_user(self, context: AuthContext) -> SessionUser:
        """Get the current authenticated user (bearer token or session)."""
        return context.user

    @provide(scope=Scope.REQUEST)
    def require_admin(self, context: AuthContext) -> AdminAccess:
        """Assert the caller has admin access; raise HTTP 403 otherwise."""
        if context.scopes is not None and ApiScope.ADMIN.value not in context.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires '{ApiScope.ADMIN.value}' scope",
            )
        return AdminAccess()

    @provide(scope=Scope.REQUEST)
    async def get_optional_user(
        self,
        request: Request,
        settings: Settings,
        verifier: JWTVerifier | None,
    ) -> SessionUser | None:
        """Get the current authenticated user if available, else None.

        Never raises: unauthenticated or invalid-credential requests resolve to
        an anonymous (None) user.
        """
        if settings.disable_auth:
            return _dev_user()

        token = _bearer_token(request)
        if token is not None and verifier is not None:
            result = await _verify_bearer(token, verifier)
            return result[0] if result is not None else None

        user_data = request.session.get("user")
        if not user_data:
            return None
        try:
            return SessionUser.model_validate(user_data)
        except pydantic.ValidationError as e:
            logger.warning("Invalid user session data", error=e, user_data=user_data)
            return None


def _session_user(request: Request) -> SessionUser:
    """Resolve the user from the session cookie, raising HTTP 401 if absent."""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return SessionUser.model_validate(user_data)
    except pydantic.ValidationError as e:
        logger.warning("Invalid user session data", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session data",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
