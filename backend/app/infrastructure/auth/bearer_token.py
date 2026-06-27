"""Bearer-token verifier construction for direct API authentication.

Builds a FastMCP :class:`JWTVerifier` for validating IdP-issued access tokens
on REST endpoints. The JWKS endpoint is resolved via OIDC discovery
(``{issuer}/.well-known/openid-configuration``) so only the issuer needs to be
configured. Returns ``None`` when bearer auth is not configured.
"""

from __future__ import annotations

import httpx
import structlog
from fastmcp.server.auth.providers.jwt import JWTVerifier

from app.infrastructure.config import Settings

logger = structlog.get_logger()

_DISCOVERY_SUFFIX = "/.well-known/openid-configuration"


def discovery_url(settings: Settings) -> str:
    """Return the OIDC discovery document URL, or empty string if unconfigured."""
    if settings.oauth_discovery_url:
        return settings.oauth_discovery_url
    if not settings.oauth_issuer:
        return ""
    return settings.oauth_issuer.rstrip("/") + _DISCOVERY_SUFFIX


async def create_jwt_verifier(
    settings: Settings,
    http_client: httpx.AsyncClient | None = None,
) -> JWTVerifier | None:
    """Create a JWTVerifier from OIDC discovery, or ``None`` if not configured.

    Raises RuntimeError if the issuer is configured but discovery fails or the
    document is missing a ``jwks_uri`` — misconfiguration should be loud.
    """
    if not settings.oauth_issuer:
        return None

    url = discovery_url(settings)
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=10.0)
    try:
        response = await client.get(url)
        response.raise_for_status()
        document = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(
            f"Failed to fetch OIDC discovery document from {url}: {exc}"
        ) from exc
    finally:
        if owns_client:
            await client.aclose()

    jwks_uri = document.get("jwks_uri")
    if not jwks_uri:
        raise RuntimeError(f"OIDC discovery document at {url} is missing 'jwks_uri'.")

    # Fail closed on issuer mismatch: a mispointed or tampered discovery
    # document could otherwise supply attacker-controlled keys (jwks_uri) while
    # tokens still carry the configured `iss`. Per OIDC, the document's issuer
    # MUST equal the configured issuer.
    advertised_issuer = document.get("issuer")
    if advertised_issuer and advertised_issuer.rstrip("/") != (
        settings.oauth_issuer.rstrip("/")
    ):
        raise RuntimeError(
            "OIDC issuer mismatch: discovery document at "
            f"{url} advertises issuer {advertised_issuer!r} but "
            f"OAUTH_ISSUER is {settings.oauth_issuer!r}. Refusing to trust its keys."
        )

    if not settings.oauth_audience:
        # No audience => JWTVerifier skips the `aud` check, so a valid token
        # minted for ANY service sharing this issuer would be accepted. Set
        # OAUTH_AUDIENCE to this API's resource identifier in production.
        logger.warning(
            "Bearer-token audience validation DISABLED (OAUTH_AUDIENCE unset). "
            "Tokens issued for other services on the same issuer will be "
            "accepted. Set OAUTH_AUDIENCE to this API's resource identifier.",
            issuer=settings.oauth_issuer,
        )

    logger.info(
        "Bearer-token auth enabled",
        issuer=settings.oauth_issuer,
        jwks_uri=jwks_uri,
        audience=settings.oauth_audience or None,
    )
    return JWTVerifier(
        jwks_uri=jwks_uri,
        issuer=settings.oauth_issuer,
        audience=settings.oauth_audience or None,
    )
