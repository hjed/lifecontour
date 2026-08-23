"""OIDC discovery rules shared by both authentication surfaces.

REST bearer tokens (:mod:`app.infrastructure.auth.bearer_token`) and the MCP
OAuth proxy (:mod:`app.mcp.auth.providers`) both verify IdP-issued JWTs against
the IdP's JWKS, and both resolve that JWKS through
``{issuer}/.well-known/openid-configuration``. The three decisions that have to
be made identically on both paths live here: where the document is, which
signing algorithm to trust, and whether the document may be trusted at all.

The helpers deliberately take plain values rather than a document, because the
two callers hold different shapes — a raw ``dict`` on the REST side and
FastMCP's parsed ``OIDCConfiguration`` on the MCP side.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.infrastructure.config import Settings

DISCOVERY_SUFFIX = "/.well-known/openid-configuration"

# Asymmetric algorithms we accept from discovery. Symmetric (HS*) algorithms
# are intentionally excluded: JWKS-based verification is asymmetric, and
# accepting HS* would open a key-confusion attack surface. This is an
# acceptance set, not a preference order — selection follows the IdP's
# advertised order (IdPs list their signing default first).
SUPPORTED_ALGORITHMS = frozenset({"ES256", "ES384", "ES512", "RS256", "RS384", "RS512"})


def discovery_url(settings: Settings) -> str:
    """Return the OIDC discovery document URL, or empty string if unconfigured.

    ``oauth_discovery_url`` wins when set, because the address the backend can
    fetch metadata from is not always the address tokens are issued under (a
    container-internal host versus the browser-facing issuer, for instance).
    """
    if settings.oauth_discovery_url:
        return settings.oauth_discovery_url
    if not settings.oauth_issuer:
        return ""
    return settings.oauth_issuer.rstrip("/") + DISCOVERY_SUFFIX


def supported_algorithms(
    advertised: Sequence[str] | None, *, source: str
) -> tuple[str, ...]:
    """Return every advertised signing algorithm we are willing to accept.

    ``id_token_signing_alg_values_supported`` is the *set* of algorithms the OP
    supports, not a declaration of the one it will use. Which algorithm a given
    client actually receives is fixed at registration
    (``id_token_signed_response_alg``) and is not published, so an OP
    advertising both RS256 and ES256 may legitimately sign this client's tokens
    with either. Callers must therefore be prepared for all of them; picking one
    would reject perfectly valid sessions.

    Order is preserved so a caller that can only accept a single algorithm has a
    sensible default to fall back on (OPs conventionally list theirs first).
    Returns empty when the OP advertises nothing, in which case the caller's
    verifier applies its own default.

    Raises:
        RuntimeError: if the OP advertises algorithms but none are supported.
            Failing loud beats silently defaulting to RS256 and then rejecting
            every token.
    """
    supported = tuple(
        dict.fromkeys(alg for alg in advertised or () if alg in SUPPORTED_ALGORITHMS)
    )
    if advertised and not supported:
        raise RuntimeError(
            f"OIDC discovery document at {source} advertises no supported "
            f"asymmetric signing algorithm (got {list(advertised)!r}; "
            f"supported: {sorted(SUPPORTED_ALGORITHMS)})."
        )
    return supported


def assert_issuer_matches(
    advertised_issuer: str | None, settings: Settings, *, source: str
) -> None:
    """Fail closed when the document disagrees with the configured issuer.

    A mispointed or tampered discovery document could otherwise supply
    attacker-controlled keys (``jwks_uri``) while tokens still carry the
    configured ``iss``. Per OIDC, the document's issuer MUST equal the
    configured issuer.

    No configured issuer means there is nothing to cross-check against — the
    discovery URL is then the trust anchor on its own.
    """
    if not advertised_issuer or not settings.oauth_issuer:
        return
    if advertised_issuer.rstrip("/") == settings.oauth_issuer.rstrip("/"):
        return
    raise RuntimeError(
        f"OIDC issuer mismatch: discovery document at {source} advertises "
        f"issuer {advertised_issuer!r} but OAUTH_ISSUER is "
        f"{settings.oauth_issuer!r}. Refusing to trust its keys."
    )
