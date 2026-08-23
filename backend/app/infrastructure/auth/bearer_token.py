"""Bearer-token verifier construction for direct API authentication.

Builds a FastMCP :class:`JWTVerifier` for validating IdP-issued access tokens
on REST endpoints. The JWKS endpoint and the token signing algorithm are both
resolved via OIDC discovery (``{issuer}/.well-known/openid-configuration``) so
only the issuer needs to be configured. Returns ``None`` when bearer auth is
not configured.

The discovery rules themselves live in
:mod:`app.infrastructure.auth.oidc_discovery`, shared with the MCP OAuth proxy.
"""

from __future__ import annotations

import httpx
import structlog
from fastmcp.server.auth.providers.jwt import JWTVerifier

from app.infrastructure.auth.oidc_discovery import (
    assert_issuer_matches,
    discovery_url,
    supported_algorithms,
)
from app.infrastructure.config import Settings

logger = structlog.get_logger()

__all__ = ["create_jwt_verifier", "discovery_url"]


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

    assert_issuer_matches(document.get("issuer"), settings, source=url)

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

    # JWTVerifier pins a single algorithm, and no discovery field publishes
    # which one the OP uses for *access* tokens, so take the first the OP
    # advertises for id_tokens as the best available signal.
    algorithms = supported_algorithms(
        document.get("id_token_signing_alg_values_supported"), source=url
    )
    algorithm = algorithms[0] if algorithms else None

    logger.info(
        "Bearer-token auth enabled",
        issuer=settings.oauth_issuer,
        jwks_uri=jwks_uri,
        audience=settings.oauth_audience or None,
        algorithm=algorithm or "RS256 (default)",
    )
    return JWTVerifier(
        jwks_uri=jwks_uri,
        issuer=settings.oauth_issuer,
        audience=settings.oauth_audience or None,
        algorithm=algorithm,
    )
