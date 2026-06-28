"""API permission scopes for direct bearer-token authentication.

Bearer access tokens issued by the IdP may carry app-scoped permissions:
``pms_read``, ``pms_write``, ``pms_admin``. Scopes are hierarchical
(``pms_admin`` ⊃ ``pms_write`` ⊃ ``pms_read``) and only apply to tokens that
carry them — session and dev users implicitly hold all scopes.

The ``pms_`` prefix uses an underscore (not a colon) because some IdPs,
notably Kanidm, reject ``:`` in scope names.
"""

from enum import StrEnum

SCOPE_PREFIX = "pms_"


class ApiScope(StrEnum):
    """App-scoped API permissions, ordered least to most privileged."""

    READ = "pms_read"
    WRITE = "pms_write"
    ADMIN = "pms_admin"


# Maps a REQUIRED scope to the set of GRANTED scopes that satisfy it. A higher-
# privileged grant satisfies lower-privileged requirements, so e.g. a required
# READ is satisfied by holding READ, WRITE, or ADMIN.
_SATISFIED_BY: dict[ApiScope, frozenset[ApiScope]] = {
    ApiScope.READ: frozenset({ApiScope.READ, ApiScope.WRITE, ApiScope.ADMIN}),
    ApiScope.WRITE: frozenset({ApiScope.WRITE, ApiScope.ADMIN}),
    ApiScope.ADMIN: frozenset({ApiScope.ADMIN}),
}

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def required_scope_for_method(method: str) -> ApiScope:
    """Return the scope required to call an endpoint with the given HTTP method.

    Safe (read-only) methods require ``pms_read``; mutating methods require
    ``pms_write``. Admin-only routes enforce ``pms_admin`` separately.
    """
    return ApiScope.READ if method.upper() in _SAFE_METHODS else ApiScope.WRITE


def token_satisfies(granted: set[str], required: ApiScope) -> bool:
    """Whether the granted scopes satisfy the required scope via the hierarchy."""
    accepted = _SATISFIED_BY[required]
    return any(scope in granted for scope in accepted)


def recognized_scopes(granted: set[str]) -> set[str]:
    """Return the subset of granted scopes that are recognized ``pms_*`` scopes."""
    return {scope for scope in granted if scope.startswith(SCOPE_PREFIX)}
