"""Unit tests for the Immich token service lazy Fernet initialisation."""

from unittest.mock import AsyncMock

import pytest

from app.infrastructure.auth.immich_token_service import (
    ImmichTokenService,
    ImmichTokenStorageError,
)


class TestImmichTokenServiceLazyFernet:
    """Verify that Fernet is lazily initialised."""

    def test_init_with_empty_key_does_not_crash(self) -> None:
        """Service should be constructable with an empty encryption key."""
        connection = AsyncMock()
        service = ImmichTokenService(connection, encryption_key="")
        # Should not raise — Fernet is not initialised until used
        assert service._fernet is None

    def test_fernet_property_raises_on_empty_key(self) -> None:
        """Accessing fernet with empty key raises ImmichTokenStorageError."""
        connection = AsyncMock()
        service = ImmichTokenService(connection, encryption_key="")

        with pytest.raises(ImmichTokenStorageError, match="not configured"):
            _ = service.fernet

    def test_fernet_property_raises_on_invalid_key(self) -> None:
        """Accessing fernet with an invalid key raises ImmichTokenStorageError."""
        connection = AsyncMock()
        service = ImmichTokenService(connection, encryption_key="not-a-valid-key")

        with pytest.raises(ImmichTokenStorageError, match="Invalid"):
            _ = service.fernet

    def test_fernet_property_succeeds_with_valid_key(self) -> None:
        """Accessing fernet with a valid key returns a Fernet instance."""
        from cryptography.fernet import Fernet

        valid_key = Fernet.generate_key().decode()
        connection = AsyncMock()
        service = ImmichTokenService(connection, encryption_key=valid_key)

        fernet = service.fernet
        assert fernet is not None
        # Second access returns cached instance
        assert service.fernet is fernet
