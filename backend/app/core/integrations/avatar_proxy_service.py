"""Avatar proxy service for Immich contact thumbnails.

Fetches person thumbnails from Immich using stored credentials,
keeping the Immich server URL and API key hidden from the browser.
"""

from __future__ import annotations

import httpx
import structlog
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = structlog.get_logger(__name__)


class AvatarNotFoundError(Exception):
    """Raised when the avatar cannot be resolved."""


class AvatarProxyService:
    """Proxy service that fetches Immich person thumbnails on behalf of the user.

    Args:
        connection: Async database connection.
        encryption_key: Fernet key for decrypting the stored Immich API key.
    """

    def __init__(self, connection: AsyncConnection, encryption_key: str) -> None:
        self._conn = connection
        self._encryption_key = encryption_key

    async def get_avatar_bytes(self, contact_id: int, user_id: str) -> bytes:
        """Fetch the Immich person thumbnail for a contact.

        Args:
            contact_id: Internal contact ID.
            user_id: Internal user ID (for credential lookup).

        Returns:
            Raw JPEG/PNG bytes of the thumbnail.

        Raises:
            AvatarNotFoundError: If the contact has no Immich link, the user
                has no Immich credentials, or the thumbnail fetch fails.
        """
        # 1. Look up the Immich person_id for this contact
        person_id = await self._get_immich_person_id(contact_id)
        if person_id is None:
            raise AvatarNotFoundError(
                f"Contact {contact_id} is not linked to an Immich person"
            )

        # 2. Get the user's Immich credentials
        server_url, api_key = await self._get_immich_credentials(user_id)
        if server_url is None or api_key is None:
            raise AvatarNotFoundError("Immich is not configured for this user")

        # 3. Fetch the thumbnail from Immich
        return await self._fetch_thumbnail(server_url, api_key, person_id)

    async def _get_immich_person_id(self, contact_id: int) -> str | None:
        """Look up the Immich person ID from external_references."""
        query = text("""
            SELECT external_entity_id
            FROM external_references
            WHERE internal_entity_type = 'contact'
              AND internal_entity_id = :contact_id
              AND external_system = 'immich'
              AND external_entity_type = 'person'
            LIMIT 1
        """)
        result = await self._conn.execute(query, {"contact_id": contact_id})
        row = result.fetchone()
        return row.external_entity_id if row else None

    async def _get_immich_credentials(
        self, user_id: str
    ) -> tuple[str | None, str | None]:
        """Fetch and decrypt the user's Immich server URL and API key."""
        query = text("""
            SELECT server_url, encrypted_api_key
            FROM user_immich_auth
            WHERE user_id = :user_id
        """)
        result = await self._conn.execute(query, {"user_id": user_id})
        row = result.fetchone()
        if row is None:
            return None, None

        try:
            fernet = Fernet(self._encryption_key.encode())
            api_key = fernet.decrypt(row.encrypted_api_key).decode()
        except (InvalidToken, ValueError) as e:
            logger.warning(
                "Failed to decrypt Immich API key for avatar proxy",
                user_id=user_id,
                error=str(e),
            )
            return None, None

        return row.server_url, api_key

    @staticmethod
    async def _fetch_thumbnail(server_url: str, api_key: str, person_id: str) -> bytes:
        """Download the person thumbnail from Immich.

        Raises:
            AvatarNotFoundError: If the Immich API returns an error.
        """
        url = f"{server_url.rstrip('/')}/api/people/{person_id}/thumbnail"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    url,
                    headers={
                        "x-api-key": api_key,
                        "Accept": "application/octet-stream",
                    },
                )
                response.raise_for_status()
                return response.content
        except httpx.HTTPStatusError as e:
            logger.warning(
                "Immich thumbnail request failed",
                person_id=person_id,
                status=e.response.status_code,
            )
            raise AvatarNotFoundError(
                f"Immich returned {e.response.status_code} for person {person_id}"
            ) from e
        except httpx.RequestError as e:
            logger.warning(
                "Immich thumbnail request error",
                person_id=person_id,
                error=str(e),
            )
            raise AvatarNotFoundError(f"Failed to connect to Immich: {e}") from e
