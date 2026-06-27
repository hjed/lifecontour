"""Shared mapping from OAuth token claims to a :class:`SessionUser`.

Used by both the MCP server (FastMCP access-token claims) and the REST API
(direct bearer-token claims) so user identity is derived identically across
authentication surfaces.
"""

from typing import Any

from app.infrastructure.auth.models import SessionUser


def session_user_from_claims(
    claims: dict[str, Any] | None,
    client_id: str | None,
    provider: str,
) -> SessionUser:
    """Build a :class:`SessionUser` from validated OAuth token claims.

    Falls back through provider-specific claim shapes:
    - id:    ``sub`` -> ``id`` -> ``client_id``
    - email: ``email`` (empty string when absent)
    - name:  ``name`` -> ``login`` -> ``username``
    """
    claims = claims or {}
    return SessionUser(
        id=str(claims.get("sub") or claims.get("id") or client_id),
        email=str(claims.get("email", "")),
        name=str(
            claims.get("name") or claims.get("login") or claims.get("username") or ""
        ),
        provider=provider,
    )
