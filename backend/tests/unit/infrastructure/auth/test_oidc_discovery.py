"""Unit tests for the OIDC discovery helpers shared by both auth surfaces.

REST bearer tokens and the MCP OAuth proxy resolve the IdP's signing keys the
same way, so the rules live in one place: where the metadata is, which signing
algorithm to trust, and whether the document may be trusted at all.
"""

import pytest

from app.infrastructure.auth.oidc_discovery import (
    assert_issuer_matches,
    discovery_url,
    supported_algorithms,
)
from app.infrastructure.config import Settings


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"oauth_issuer": "", "oauth_discovery_url": ""}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestDiscoveryUrl:
    def test_empty_when_no_issuer(self) -> None:
        assert discovery_url(_settings()) == ""

    def test_derived_from_issuer(self) -> None:
        url = discovery_url(_settings(oauth_issuer="https://idp.example.com/"))
        assert url == "https://idp.example.com/.well-known/openid-configuration"

    def test_derived_from_a_kanidm_client_scoped_issuer(self) -> None:
        """Kanidm's issuer is per client, so the suffix appends to a path."""
        url = discovery_url(
            _settings(oauth_issuer="https://idm.example.com/oauth2/openid/pms")
        )
        assert url == (
            "https://idm.example.com/oauth2/openid/pms/.well-known/openid-configuration"
        )

    def test_explicit_override_wins(self) -> None:
        """The backend may have to fetch metadata from a different address."""
        url = discovery_url(
            _settings(
                oauth_issuer="http://localhost:4444",
                oauth_discovery_url=(
                    "http://pms-oauth:4444/.well-known/openid-configuration"
                ),
            )
        )
        assert url == "http://pms-oauth:4444/.well-known/openid-configuration"

    def test_override_alone_is_enough(self) -> None:
        url = discovery_url(_settings(oauth_discovery_url="https://idp/meta"))
        assert url == "https://idp/meta"


class TestSupportedAlgorithms:
    """Discovery publishes what the OP *supports*, not what this client gets.

    Which algorithm a given client receives is fixed at registration
    (``id_token_signed_response_alg``) and is never published, so an OP
    advertising both RS256 and ES256 may legitimately sign this client's tokens
    with either. Callers have to be ready for all of them.
    """

    def test_empty_when_nothing_advertised(self) -> None:
        """The caller's verifier then applies its own default."""
        assert supported_algorithms(None, source="https://idp/meta") == ()
        assert supported_algorithms([], source="https://idp/meta") == ()

    def test_returns_every_advertised_algorithm_we_accept(self) -> None:
        assert supported_algorithms(["RS256", "ES256"], source="s") == (
            "RS256",
            "ES256",
        )

    def test_preserves_the_idp_ordering(self) -> None:
        """Callers pinned to one algorithm fall back on the OP's first."""
        assert supported_algorithms(["ES256", "RS256"], source="s")[0] == "ES256"
        assert supported_algorithms(["RS256", "ES256"], source="s")[0] == "RS256"

    def test_drops_algorithms_we_do_not_accept(self) -> None:
        assert supported_algorithms(["EdDSA", "ES256"], source="s") == ("ES256",)

    def test_drops_duplicates(self) -> None:
        assert supported_algorithms(["RS256", "RS256"], source="s") == ("RS256",)

    def test_rejects_symmetric_algorithms(self) -> None:
        """HS* with JWKS verification would open a key-confusion hole."""
        with pytest.raises(RuntimeError, match="signing algorithm"):
            supported_algorithms(["HS256"], source="https://idp/meta")

    def test_raises_when_nothing_advertised_is_supported(self) -> None:
        """Failing loud beats defaulting to RS256 and rejecting every token."""
        with pytest.raises(RuntimeError, match="signing algorithm"):
            supported_algorithms(["EdDSA"], source="https://idp/meta")


class TestAssertIssuerMatches:
    def test_accepts_an_exact_match(self) -> None:
        assert_issuer_matches(
            "https://idp.example.com",
            _settings(oauth_issuer="https://idp.example.com"),
            source="https://idp/meta",
        )

    def test_ignores_a_trailing_slash(self) -> None:
        assert_issuer_matches(
            "https://idp.example.com/",
            _settings(oauth_issuer="https://idp.example.com"),
            source="https://idp/meta",
        )

    def test_accepts_a_document_that_omits_the_issuer(self) -> None:
        assert_issuer_matches(
            None,
            _settings(oauth_issuer="https://idp.example.com"),
            source="https://idp/meta",
        )

    def test_accepts_when_no_issuer_is_configured(self) -> None:
        """Nothing to compare against — the discovery URL is the trust anchor."""
        assert_issuer_matches("https://idp.example.com", _settings(), source="s")

    def test_rejects_a_mismatch(self) -> None:
        """Fail closed: a mispointed document could supply attacker keys."""
        with pytest.raises(RuntimeError, match="issuer mismatch"):
            assert_issuer_matches(
                "https://evil.example.com",
                _settings(oauth_issuer="https://idp.example.com"),
                source="https://idp/meta",
            )
