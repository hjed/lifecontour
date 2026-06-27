"""API permission scopes for direct bearer-token authentication.

Bearer access tokens issued by the IdP may carry app-scoped permissions:
``pms:read``, ``pms:write``, ``pms:admin``. Scopes are hierarchical
(``pms:admin`` ⊃ ``pms:write`` ⊃ ``pms:read``) and only apply to tokens that
carry them — session and dev users implicitly hold all scopes.
"""

from enum import StrEnum

SCOPE_PREFIX = "pms:"


class ApiScope(StrEnum):
    """App-scoped API permissions, ordered least to most privileged."""

    READ = "pms:read"
    WRITE = "pms:write"
    ADMIN = "pms:admin"


# Each scope implicitly grants itself and every lower-privileged scope.
_IMPLIED_BY: dict[ApiScope, frozenset[ApiScope]] = {
    ApiScope.READ: frozenset({ApiScope.READ, ApiScope.WRITE, ApiScope.ADMIN}),
    ApiScope.WRITE: frozenset({ApiScope.WRITE, ApiScope.ADMIN}),
    ApiScope.ADMIN: frozenset({ApiScope.ADMIN}),
}

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def required_scope_for_method(method: str) -> ApiScope:
    """Return the scope required to call an endpoint with the given HTTP method.

    Safe (read-only) methods require ``pms:read``; mutating methods require
    ``pms:write``. Admin-only routes enforce ``pms:admin`` separately.
    """
    return ApiScope.READ if method.upper() in _SAFE_METHODS else ApiScope.WRITE


def token_satisfies(granted: set[str], required: ApiScope) -> bool:
    """Whether the granted scopes satisfy the required scope via the hierarchy."""
    accepted = _IMPLIED_BY[required]
    return any(scope in granted for scope in accepted)


def recognized_scopes(granted: set[str]) -> set[str]:
    """Return the subset of granted scopes that are recognized ``pms:*`` scopes."""
    return {scope for scope in granted if scope.startswith(SCOPE_PREFIX)}
