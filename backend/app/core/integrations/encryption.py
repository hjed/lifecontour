"""
Encryption service for secure token storage.

Provides Fernet-based symmetric encryption for storing sensitive data
like OAuth tokens in the database.
"""

import structlog
from cryptography.fernet import Fernet, InvalidToken

from app.infrastructure.config import Settings

logger = structlog.get_logger()


class EncryptionError(Exception):
    """Custom exception for encryption/decryption failures."""

    pass


class EncryptionService:
    """
    Service for encrypting and decrypting sensitive data using Fernet.

    Uses symmetric encryption with a key from application settings.
    All encrypted data is returned as bytes for database storage.
    """

    def __init__(self, settings: Settings) -> None:
        """
        Initialize encryption service with settings.

        Args:
            settings: Application settings containing encryption key

        Raises:
            EncryptionError: If encryption key is invalid or missing
        """
        try:
            # Get encryption key from settings
            if not settings.google_encryption_key:
                raise EncryptionError(
                    "Google encryption key not configured. "
                    "Set GOOGLE_ENCRYPTION_KEY environment variable."
                )

            # Key must be 32 URL-safe base64-encoded bytes
            key_bytes = settings.google_encryption_key.encode("utf-8")
            self._fernet = Fernet(key_bytes)

            logger.info("Encryption service initialized successfully")

        except Exception as e:
            logger.error("Failed to initialize encryption service", error=str(e))
            raise EncryptionError("Failed to initialize encryption service") from e

    def encrypt(self, data: str) -> bytes:
        """
        Encrypt a string and return bytes for database storage.

        Args:
            data: String data to encrypt

        Returns:
            Encrypted data as bytes

        Raises:
            EncryptionError: If encryption fails
        """
        try:
            if not data:
                raise EncryptionError("Cannot encrypt empty data")

            return self._fernet.encrypt(data.encode("utf-8"))

        except Exception as e:
            logger.error("Failed to encrypt data", error=str(e))
            raise EncryptionError("Failed to encrypt data") from e

    def decrypt(self, encrypted_data: bytes) -> str:
        """
        Decrypt bytes and return the original string.

        Args:
            encrypted_data: Encrypted data as bytes

        Returns:
            Decrypted string data

        Raises:
            EncryptionError: If decryption fails or data is invalid
        """
        try:
            if not encrypted_data:
                raise EncryptionError("Cannot decrypt empty data")

            decrypted_bytes = self._fernet.decrypt(encrypted_data)
            return decrypted_bytes.decode("utf-8")

        except InvalidToken as e:
            logger.error("Failed to decrypt data: Invalid token")
            raise EncryptionError("Failed to decrypt data: Invalid token") from e
        except Exception as e:
            logger.error("Failed to decrypt data", error=str(e))
            raise EncryptionError("Failed to decrypt data") from e

    @staticmethod
    def generate_key() -> str:
        """
        Generate a new Fernet encryption key.

        This should be called once to generate a key for production use.
        The key should be stored securely and not regenerated.

        Returns:
            Base64-encoded encryption key as string
        """
        return Fernet.generate_key().decode("utf-8")


def generate_encryption_key() -> str:
    """
    Utility function to generate a new encryption key.

    This is a convenience function for key generation scripts.

    Returns:
        Base64-encoded encryption key as string
    """
    return EncryptionService.generate_key()
