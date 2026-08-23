"""
MCP OAuth provider factory.

Creates the appropriate FastMCP auth provider based on application settings.
Uses FastMCP's built-in OAuth proxy providers (GitHubProvider, AzureProvider,
DiscordProvider) which handle .well-known discovery, authorization flows,
token issuance, and consent screens.

The generic-OAuth path uses FastMCP's :class:`OIDCProxy`, which discovers the
upstream IdP's configuration and verifies its tokens against the advertised
JWKS. See :class:`McpOidcProxy` for the two things it needs on top of that.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import structlog
from cryptography.fernet import Fernet
from fastmcp.server.auth.auth import AccessToken, AuthProvider, TokenVerifier
from fastmcp.server.auth.jwt_issuer import derive_jwt_key
from fastmcp.server.auth.oauth_proxy.models import UpstreamTokenSet
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration, OIDCProxy
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.auth.providers.discord import DiscordProvider
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.utilities.auth import decode_jwt_header, decode_jwt_payload
from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.stores.redis import RedisStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from pydantic import AnyHttpUrl

from app.infrastructure.auth.oidc_discovery import (
    assert_issuer_matches,
    discovery_url,
    supported_algorithms,
)
from app.infrastructure.config import Settings

logger = structlog.get_logger()

# Salt for deriving the OAuth-state encryption key from the signing key.
# Distinct from FastMCP's internal salts so the keys never collide.
_STORAGE_ENCRYPTION_SALT = "mcp-oauth-storage-encryption"


class _LoggingFernetEncryptionWrapper(FernetEncryptionWrapper):
    """Fernet wrapper that logs (instead of silently dropping) decrypt failures.

    We keep ``raise_on_decryption_error=False`` so a key mismatch or corrupt
    entry degrades to re-registration rather than crashing requests (matching
    FastMCP's own file-store behaviour). But a silent drop of persisted refresh
    tokens looks like a re-auth loop, so we surface it as a warning to make a
    rotated/mismatched MCP_JWT_SIGNING_KEY diagnosable.
    """

    def _decrypt_value(
        self, value: dict[str, object] | None
    ) -> dict[str, object] | None:
        result = super()._decrypt_value(value)
        # A non-None input that decrypts to None only happens on the
        # decryption-failure branch (a genuine miss returns None for None input,
        # and unencrypted dicts are returned as-is).
        if value is not None and result is None:
            logger.warning(
                "MCP: failed to decrypt persisted OAuth state; treating it as a "
                "cache miss. Affected MCP clients must re-authenticate. This "
                "usually means MCP_JWT_SIGNING_KEY changed or the stored data "
                "is corrupt."
            )
        return result


class _UnacceptableAlgorithmError(Exception):
    """A token was signed with an algorithm the IdP does not advertise."""


def _header_algorithm(token: str) -> str | None:
    """The ``alg`` a JWT claims in its header, or None if it cannot be read."""
    try:
        algorithm = decode_jwt_header(token).get("alg")
    except Exception:  # noqa: BLE001 - malformed: let the verifier reject it
        return None
    return algorithm if isinstance(algorithm, str) else None


class _IdTokenVerifier(JWTVerifier):
    """A ``JWTVerifier`` that also enforces the ID Token rules OIDC requires.

    ``JWTVerifier`` is a general-purpose JWT checker, so two rules from OIDC
    Core fall outside it. Both matter here because the ID Token is the whole
    basis on which an MCP request authenticates.

    - ``exp`` is REQUIRED in an ID Token (Core §2), but the verifier only
      compares it *when present*. An ID Token minted without one would
      authenticate forever — outliving the upstream grant it stands for, and
      surviving the refresh failure that is otherwise what ends a dead session.
    - When ``aud`` holds more than one value the ID Token must carry ``azp``,
      and when ``azp`` is present it must be this client (Core §3.1.3.7). The
      verifier only checks that our client id appears *somewhere* in ``aud``,
      so without this a token minted for a different relying party that happens
      to list us alongside itself would authenticate here.

    Both are checked against the payload the signature check already validated,
    never against a raw decode.

    It also accepts **any** of the algorithms the OP advertises rather than one.
    ``JWTVerifier`` pins a single algorithm, but discovery publishes the set the
    OP supports, not the one this client gets — that is fixed at registration
    and never published. So one verifier is kept per advertised algorithm and
    the token's own ``alg`` header chooses. The advertised set is still the
    guard: an algorithm outside it never reaches a verifier at all, which is
    what keeps a token from selecting, say, a symmetric algorithm that JWKS
    verification cannot safely use.
    """

    def __init__(
        self,
        *,
        authorized_party: str,
        algorithms: Sequence[str] = (),
        **kwargs: Any,
    ) -> None:
        accepted = tuple(dict.fromkeys(algorithms))
        # An empty set means the OP advertised nothing; JWTVerifier's own
        # default (RS256) then stands, and self is the only verifier.
        super().__init__(algorithm=accepted[0] if accepted else None, **kwargs)
        self._authorized_party = authorized_party
        self._accepted_algorithms = frozenset(accepted)
        self._verifier_kwargs = kwargs
        self._delegates: dict[str, JWTVerifier] = {}

    def _verifier_for(self, algorithm: str | None) -> JWTVerifier | None:
        """The verifier for a token's ``alg``, or None if we do not accept it."""
        if algorithm is None or algorithm == self.algorithm:
            return None  # our own super() handles it
        if algorithm not in self._accepted_algorithms:
            logger.warning(
                "MCP: refusing an upstream id_token signed with an algorithm "
                "the IdP does not advertise.",
                algorithm=algorithm,
                accepted=sorted(self._accepted_algorithms),
            )
            raise _UnacceptableAlgorithmError
        delegate = self._delegates.get(algorithm)
        if delegate is None:
            delegate = JWTVerifier(algorithm=algorithm, **self._verifier_kwargs)
            self._delegates[algorithm] = delegate
        return delegate

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Verify the JWT, then apply the ID Token rules on its verified claims."""
        try:
            delegate = self._verifier_for(_header_algorithm(token))
        except _UnacceptableAlgorithmError:
            return None
        verified = (
            await super().load_access_token(token)
            if delegate is None
            else await delegate.load_access_token(token)
        )
        if verified is None:
            return None

        claims = verified.claims or {}

        if claims.get("exp") is None:
            logger.warning(
                "MCP: refusing an upstream id_token with no 'exp' claim. OIDC "
                "requires one; without it the token would never expire and the "
                "MCP session could outlive the upstream grant indefinitely.",
                subject=claims.get("sub"),
            )
            return None

        audience = claims.get("aud")
        authorized_party = claims.get("azp")
        if authorized_party is None:
            if isinstance(audience, list) and len(audience) > 1:
                logger.warning(
                    "MCP: refusing an upstream id_token with several audiences "
                    "and no 'azp' claim, so the party it was issued to cannot "
                    "be established.",
                    audience=audience,
                )
                return None
        elif authorized_party != self._authorized_party:
            logger.warning(
                "MCP: refusing an upstream id_token issued to a different "
                "relying party.",
                authorized_party=authorized_party,
                expected=self._authorized_party,
            )
            return None

        return verified


class McpOidcProxy(OIDCProxy):
    """An ``OIDCProxy`` that trusts the IdP's own metadata about its keys.

    Two gaps in the stock proxy matter here:

    - It builds its ``JWTVerifier`` without an algorithm, and ``JWTVerifier``
      falls back to RS256. Kanidm signs id_tokens with **ES256** unless legacy
      crypto is enabled, so production would reject every token while Hydra
      (which advertises RS256 only) looked perfectly healthy in dev. The
      algorithm therefore comes from the document, honoring the IdP's ordering.
    - It treats the discovery URL as the sole trust anchor. In dev that
      document is fetched from a container-internal address that is not the
      issuer tokens are minted under, so the issuer it advertises is
      cross-checked against ``OAUTH_ISSUER`` before its keys are trusted.

    Its verifier is :class:`_IdTokenVerifier` rather than a bare
    ``JWTVerifier``, and it makes one failure mode diagnosable — see
    :meth:`_get_verification_token`.
    """

    def __init__(self, *, settings: Settings, **kwargs: Any) -> None:
        # Assigned before super().__init__ because discovery — and with it both
        # hooks below — runs inside the parent constructor.
        self._settings = settings
        super().__init__(**kwargs)

    def get_oidc_configuration(
        self,
        config_url: AnyHttpUrl,
        strict: bool | None,
        timeout_seconds: int | None,
    ) -> OIDCConfiguration:
        """Fetch the document, then refuse it if it disowns the issuer."""
        config = super().get_oidc_configuration(config_url, strict, timeout_seconds)
        assert_issuer_matches(
            str(config.issuer) if config.issuer else None,
            self._settings,
            source=str(config_url),
        )
        return config

    def _get_verification_token(
        self, upstream_token_set: UpstreamTokenSet
    ) -> str | None:
        """Return the id_token to verify, warning when it has gone stale.

        OIDC lets a refresh response omit ``id_token``, and FastMCP *merges*
        each response into ``raw_token_data`` — so with such an IdP a refresh
        succeeds, resets the access token's expiry, and leaves the **old**
        id_token in place. Verification then fails on an expired id_token while
        the refresh that would replace it is not due again until the fresh
        access token nears expiry, so the session 401s for that whole window.

        Neither IdP this project targets behaves that way (Hydra reissues the
        id_token on refresh; Kanidm is expected to), and the semantics are
        FastMCP's rather than ours. But the symptom — sudden re-auth despite a
        healthy refresh — gives no clue as to its cause, so name it in the log.
        """
        token = super()._get_verification_token(upstream_token_set)
        if (
            token is not None
            and _is_expired(token)
            and upstream_token_set.expires_at > time.time()
        ):
            logger.warning(
                "MCP: the stored upstream id_token has expired while its "
                "access token has not. The IdP most likely omitted id_token "
                "from a refresh response, which leaves the previous one in "
                "place. MCP requests will fail to authenticate until the "
                "access token expires and a full re-auth happens.",
                access_token_expires_at=upstream_token_set.expires_at,
            )
        return token

    def get_token_verifier(
        self,
        *,
        algorithm: str | None = None,
        audience: str | None = None,
        required_scopes: list[str] | None = None,
        timeout_seconds: int | None = None,
    ) -> TokenVerifier:
        """Build the verifier: IdP-advertised algorithm, ID Token rules enforced."""
        del timeout_seconds  # unused by the parent too; JWKS fetches set their own
        return _IdTokenVerifier(
            authorized_party=self._settings.oauth_client_id,
            jwks_uri=str(self.oidc_config.jwks_uri),
            issuer=str(self.oidc_config.issuer),
            algorithms=(algorithm,)
            if algorithm
            else supported_algorithms(
                self.oidc_config.id_token_signing_alg_values_supported,
                source=str(self.oidc_config.issuer),
            ),
            audience=audience,
            required_scopes=required_scopes,
        )


def _is_expired(token: str, *, now: float | None = None) -> bool:
    """Whether a JWT's ``exp`` has passed. Undecodable or unbounded => False."""
    try:
        payload = decode_jwt_payload(token)
    except Exception:  # noqa: BLE001 - opaque or malformed: nothing to say
        return False
    exp = payload.get("exp")
    if not isinstance(exp, int | float):
        return False
    return exp <= (time.time() if now is None else now)


def create_mcp_auth_provider(settings: Settings) -> AuthProvider | None:
    """Create the MCP auth provider based on configured OAuth settings.

    Returns the first available provider in priority order:
    Generic OAuth > GitHub > Microsoft > Discord.

    Returns None if auth is disabled or no providers are configured.

    Args:
        settings: Application settings containing OAuth credentials

    Returns:
        Configured AuthProvider or None
    """
    if settings.disable_auth:
        logger.info("MCP: Auth disabled, no provider created")
        return None

    base_url = _get_mcp_base_url(settings)
    if not base_url:
        if _has_any_provider_configured(settings):
            raise RuntimeError(
                "WEBHOOK_BASE_URL must be configured to use MCP OAuth auth. "
                "Set WEBHOOK_BASE_URL or disable auth explicitly via "
                "DISABLE_AUTH=true."
            )
        logger.info("MCP: No OAuth providers configured, MCP auth unavailable")
        return None

    # Priority 1: Generic OAuth provider
    if settings.oauth_client_id and settings.oauth_client_secret:
        return _create_generic_oauth_provider(settings, base_url)

    # Priority 2: GitHub
    if settings.github_client_id and settings.github_client_secret:
        logger.info("MCP: Configuring GitHub OAuth provider")
        return GitHubProvider(
            client_id=settings.github_client_id,
            client_secret=settings.github_client_secret,
            base_url=base_url,
            issuer_url=_get_mcp_issuer_url(settings),
        )

    # Priority 3: Microsoft / Azure AD
    if settings.microsoft_client_id and settings.microsoft_client_secret:
        logger.info(
            "MCP: Configuring Microsoft OAuth provider",
            tenant_id=settings.microsoft_tenant_id,
        )
        return AzureProvider(
            client_id=settings.microsoft_client_id,
            client_secret=settings.microsoft_client_secret,
            tenant_id=settings.microsoft_tenant_id,
            base_url=base_url,
            issuer_url=_get_mcp_issuer_url(settings),
            required_scopes=["openid", "profile", "email"],
        )

    # Priority 4: Discord
    if settings.discord_client_id and settings.discord_client_secret:
        logger.info("MCP: Configuring Discord OAuth provider")
        return DiscordProvider(
            client_id=settings.discord_client_id,
            client_secret=settings.discord_client_secret,
            base_url=base_url,
            issuer_url=_get_mcp_issuer_url(settings),
        )

    logger.info("MCP: No OAuth providers configured, MCP auth unavailable")
    return None


def _create_generic_oauth_provider(settings: Settings, base_url: str) -> McpOidcProxy:
    """Build the generic-OAuth proxy, or raise if its tokens can't be verified."""
    config_url = discovery_url(settings)
    if not config_url:
        raise RuntimeError(
            "Generic OAuth is configured for MCP but OIDC discovery is not. "
            "Set OAUTH_ISSUER (or OAUTH_DISCOVERY_URL) so upstream tokens can "
            "be verified against the IdP's JWKS. Without it the MCP server has "
            "no way to check the upstream token at all."
        )
    logger.info(
        "MCP: Configuring generic OAuth provider",
        provider_name=settings.oauth_provider_name or "generic",
        discovery_url=config_url,
    )
    return McpOidcProxy(
        settings=settings,
        config_url=config_url,
        client_id=settings.oauth_client_id,
        client_secret=settings.oauth_client_secret,
        # Verify the id_token rather than the access token. Under OIDC the
        # id_token is always a JWT, whereas the access token may be opaque
        # — Hydra's are — and so cannot be verified at all. Its `aud` is the
        # OAuth client_id (OIDC Core 2), which OIDCProxy configures the
        # verifier with. The verified claims also carry the acting user's
        # identity, so nothing has to decode an unverified token for it.
        #
        # Note this is signature-and-expiry verification against the IdP's
        # JWKS, not a liveness check: revoking a session upstream does not
        # retire the signing key, so an already-issued id_token stays valid
        # until its `exp`. Revocation surfaces at the next refresh, which the
        # IdP refuses — bounded by the upstream token lifetime, not immediate.
        # Detecting it sooner needs introspection or userinfo per request (#1322).
        verify_id_token=True,
        base_url=base_url,
        issuer_url=_get_mcp_issuer_url(settings),
        extra_authorize_params={"scope": settings.oauth_scopes}
        if settings.oauth_scopes
        else None,
        # Refresh the upstream token shortly before it expires so MCP
        # sessions survive without a full re-auth (relies on the upstream
        # issuing a refresh token).
        token_expiry_threshold_seconds=(settings.oauth_token_refresh_threshold_seconds),
        # Pin the signing key so issued tokens stay valid across restarts;
        # None preserves FastMCP's HKDF-from-client-secret default.
        jwt_signing_key=settings.mcp_jwt_signing_key or None,
        # Persist client registrations and refresh tokens in Redis so they
        # survive restarts/redeploys instead of the per-container file store.
        client_storage=_build_mcp_client_storage(settings),
    )


def _build_mcp_client_storage(settings: Settings) -> AsyncKeyValue | None:
    """Build the persistent storage backend for OAuth-proxy state.

    Returns a Redis-backed, Fernet-encrypted store so client registrations and
    refresh tokens survive restarts/redeploys and are shared across replicas.

    FastMCP only encrypts the file store it creates itself; a caller-supplied
    ``client_storage`` is used verbatim, so we must wrap Redis in encryption
    ourselves to avoid persisting refresh tokens in plaintext.

    Returns None (FastMCP's encrypted on-disk file store) when Redis storage is
    disabled or no signing key is configured to derive the encryption key from.
    """
    if not settings.mcp_oauth_use_redis_storage:
        return None
    if not settings.mcp_jwt_signing_key:
        logger.warning(
            "MCP: Redis OAuth storage requested but MCP_JWT_SIGNING_KEY is "
            "unset; falling back to the on-disk file store to keep refresh "
            "tokens encrypted."
        )
        return None

    encryption_key = derive_jwt_key(
        low_entropy_material=settings.mcp_jwt_signing_key,
        salt=_STORAGE_ENCRYPTION_SALT,
    )
    store = RedisStore(
        url=settings.redis_url,
        default_collection="mcp-oauth-proxy",
    )
    logger.info("MCP: Using Redis-backed OAuth-proxy storage")
    return _LoggingFernetEncryptionWrapper(
        key_value=store,
        fernet=Fernet(key=encryption_key),
        raise_on_decryption_error=False,
    )


def _get_mcp_base_url(settings: Settings) -> str:
    """Compute the MCP base URL from settings.

    The base_url includes the mount path prefix so OAuth endpoints
    (authorize, token, callback) are under the mount path.

    Returns empty string if webhook_base_url is not configured.
    """
    if not settings.webhook_base_url:
        return ""
    base = settings.webhook_base_url.rstrip("/")
    mount = settings.mcp_mount_path.rstrip("/")
    return f"{base}{mount}"


def _get_mcp_issuer_url(settings: Settings) -> str:
    """Compute the MCP issuer URL from settings.

    The issuer_url is the root URL WITHOUT the mount path prefix.
    Per RFC 8414, path-aware discovery uses the issuer to construct
    .well-known paths. Setting this to the root URL ensures discovery
    works with path-aware clients.
    """
    if not settings.webhook_base_url:
        return ""
    return settings.webhook_base_url.rstrip("/")


def _has_any_provider_configured(settings: Settings) -> bool:
    """Check if any OAuth provider credentials are configured."""
    return bool(
        (settings.oauth_client_id and settings.oauth_client_secret)
        or (settings.github_client_id and settings.github_client_secret)
        or (settings.microsoft_client_id and settings.microsoft_client_secret)
        or (settings.discord_client_id and settings.discord_client_secret)
    )
