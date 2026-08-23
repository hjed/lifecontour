"""Shared mapping from OAuth token claims to a :class:`SessionUser`.

Used by both the MCP server (FastMCP access-token claims) and the REST API
(direct bearer-token claims) so user identity is derived identically across
authentication surfaces.
"""

from typing import Any

import structlog

from app.infrastructure.auth.models import SessionUser

logger = structlog.get_logger()


def session_user_from_claims(
    claims: dict[str, Any] | None,
    client_id: str | None,
    provider: str,
) -> SessionUser:
    """Build a :class:`SessionUser` from validated OAuth token claims.

    Falls back through provider-specific claim shapes:
    - id:    ``sub`` -> ``id``
    - email: ``email`` (empty string when absent)
    - name:  ``name`` -> ``login`` -> ``username``

    ``client_id`` is deliberately **not** part of the identity chain. It names
    the application, never the person using it, so accepting it made every
    caller sharing an OAuth client look like one user. That is exactly what
    happened on the MCP surface: ``DebugTokenVerifier`` supplies no identity
    claims and its own default ``client_id="debug-client"``, so from 2026-03-20
    every MCP write was attributed to a phantom owner of that name — unreachable
    from the signed-in user's owner-scoped reads. It is kept as a parameter for
    logging and for callers that pass it positionally.

    Raises:
        ValueError: if no usable identifier can be derived, so an unidentified
            token is refused rather than resolving to something that is not a
            user.
    """
    claims = claims or {}
    identifier = claims.get("sub") or claims.get("id")
    if not identifier:
        logger.warning(
            "Token carries no user identity claim; refusing it",
            provider=provider,
            client_id=client_id,
            claim_names=sorted(claims),
        )
        raise ValueError("Token has no usable identifier (sub/id)")
    return SessionUser(
        id=str(identifier),
        # `or ""` (not a get default) so a present-but-null claim normalizes to
        # "" rather than the literal string "None".
        email=str(claims.get("email") or ""),
        name=str(
            claims.get("name") or claims.get("login") or claims.get("username") or ""
        ),
        provider=provider,
    )
