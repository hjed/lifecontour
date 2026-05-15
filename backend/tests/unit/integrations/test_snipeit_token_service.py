"""Unit tests for SnipeItTokenService.

Tests token encryption/decryption and error handling without
requiring a database connection.
"""

import pytest
from cryptography.fernet import Fernet

from app.infrastructure.auth.snipeit_token_service import (
    SnipeItTokenService,
    SnipeItTokenStorageError,
)


@pytest.fixture
def encryption_key() -> str:
    """Generate a valid Fernet key for testing."""
    return Fernet.generate_key().decode()


@pytest.fixture
def token_service(encryption_key: str) -> SnipeItTokenService:
    """Create a SnipeItTokenService with a mock connection."""
    # connection=None is fine for encryption-only tests
    return SnipeItTokenService(connection=None, encryption_key=encryption_key)  # type: ignore[arg-type]


class TestEncryption:
    """Tests for Fernet encryption/decryption functionality."""

    def test_encrypt_and_decrypt_roundtrip(
        self, token_service: SnipeItTokenService
    ) -> None:
        """Encrypting then decrypting a value returns the original."""
        original = "test-access-token-abc123"
        encrypted = token_service.encrypt(original)
        decrypted = token_service.decrypt(encrypted)
        assert decrypted == original

    def test_encrypt_produces_different_ciphertext(
        self, token_service: SnipeItTokenService
    ) -> None:
        """Two encryptions of the same value produce different ciphertext (Fernet uses random IV)."""
        value = "same-value"
        ciphertext_1 = token_service.encrypt(value)
        ciphertext_2 = token_service.encrypt(value)
        assert ciphertext_1 != ciphertext_2

    def test_decrypt_wrong_key_raises(self, encryption_key: str) -> None:
        """Decrypting with a different key raises an error."""
        service_a = SnipeItTokenService(connection=None, encryption_key=encryption_key)  # type: ignore[arg-type]
        different_key = Fernet.generate_key().decode()
        service_b = SnipeItTokenService(connection=None, encryption_key=different_key)  # type: ignore[arg-type]

        encrypted = service_a.encrypt("secret-token")

        from cryptography.fernet import InvalidToken

        with pytest.raises(InvalidToken):
            service_b.decrypt(encrypted)

    def test_fernet_lazy_initialization_empty_key_raises(self) -> None:
        """Service initialised with empty key raises SnipeItTokenStorageError on first encrypt."""
        service = SnipeItTokenService(connection=None, encryption_key="")  # type: ignore[arg-type]
        with pytest.raises(SnipeItTokenStorageError, match="not configured"):
            service.encrypt("some-value")
