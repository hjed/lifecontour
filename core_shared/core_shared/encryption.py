"""
Encryption utilities for secure token storage.

Provides Fernet-based symmetric encryption for storing sensitive data
like OAuth tokens. Used by both the main application and integration workers.
"""

from typing import Protocol

from cryptography.fernet import Fernet


class EncryptionServiceProtocol(Protocol):
    """Protocol for encryption services."""

    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt a plaintext string to bytes."""
        ...

    def decrypt(self, ciphertext: bytes) -> str:
        """Decrypt bytes back to plaintext string."""
        ...


class FernetEncryptionService:
    """
    Fernet-based encryption service for secure token storage.

    Uses symmetric encryption with a 32-byte key. The key should be
    generated using `cryptography.fernet.Fernet.generate_key()` and
    stored securely (e.g., in environment variables or secrets manager).

    Example:
        >>> from cryptography.fernet import Fernet
        >>> key = Fernet.generate_key()  # Generate once, store securely
        >>> service = FernetEncryptionService(key.decode())
        >>> encrypted = service.encrypt("my-secret-token")
        >>> decrypted = service.decrypt(encrypted)
        >>> assert decrypted == "my-secret-token"
    """

    def __init__(self, encryption_key: str) -> None:
        """
        Initialize the encryption service.

        Args:
            encryption_key: Base64-encoded 32-byte Fernet key.
                           Generate with `Fernet.generate_key().decode()`.
        """
        self._fernet = Fernet(encryption_key.encode())

    def encrypt(self, plaintext: str) -> bytes:
        """
        Encrypt a plaintext string to bytes.

        Args:
            plaintext: The string to encrypt.

        Returns:
            Encrypted bytes suitable for database storage.
        """
        result: bytes = self._fernet.encrypt(plaintext.encode())
        return result

    def decrypt(self, ciphertext: bytes) -> str:
        """
        Decrypt bytes back to plaintext string.

        Args:
            ciphertext: The encrypted bytes from `encrypt()`.

        Returns:
            Original plaintext string.

        Raises:
            cryptography.fernet.InvalidToken: If decryption fails
                (wrong key, corrupted data, or tampered ciphertext).
        """
        decrypted: bytes = self._fernet.decrypt(ciphertext)
        return decrypted.decode()


def generate_encryption_key() -> str:
    """
    Generate a new Fernet encryption key.

    This should only be called once during initial setup.
    Store the generated key securely and use it for all
    encryption/decryption operations.

    Returns:
        Base64-encoded 32-byte key string.
    """
    key: bytes = Fernet.generate_key()
    return key.decode()
