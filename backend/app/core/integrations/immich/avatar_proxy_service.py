"""Avatar proxy service for Immich contact thumbnails.

Fetches person thumbnails from Immich using stored credentials,
keeping the Immich server URL and API key hidden from the browser.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
import structlog
from core_shared.repositories.external_reference_repository import (
    ExternalReferenceRepository,
)

from app.infrastructure.auth.immich_token_service import ImmichTokenService

logger = structlog.get_logger(__name__)


class AvatarNotFoundError(Exception):
    """Raised when the avatar cannot be resolved."""


class AvatarProxyService:
    """Proxy service that fetches Immich person thumbnails on behalf of the user.

    Uses ``ExternalReferenceRepository`` for person-ID lookups and
    ``ImmichTokenService`` for credential resolution — no ad-hoc SQL.

    Args:
        ext_ref_repo: Repository for external reference lookups.
        immich_token_service: Service for Immich credential management.
    """

    def __init__(
        self,
        ext_ref_repo: ExternalReferenceRepository,
        immich_token_service: ImmichTokenService,
    ) -> None:
        self._ext_ref_repo = ext_ref_repo
        self._token_service = immich_token_service

    async def get_avatar_bytes(
        self, contact_id: int, user_id: str
    ) -> tuple[bytes, str]:
        """Fetch the Immich person thumbnail for a contact.

        Args:
            contact_id: Internal contact ID.
            user_id: Internal user ID (for credential lookup).

        Returns:
            Tuple of (raw image bytes, content-type string).

        Raises:
            AvatarNotFoundError: If the contact has no Immich link, the user
                has no Immich credentials, or the thumbnail fetch fails.
        """
        # 1. Look up the Immich person_id for this contact
        person_id = await self._ext_ref_repo.get_immich_person_id(contact_id)
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

    async def _get_immich_credentials(
        self, user_id: str
    ) -> tuple[str | None, str | None]:
        """Fetch and decrypt the user's Immich server URL and API key.

        Delegates to ImmichTokenService for credential retrieval.
        """
        try:
            return await self._token_service.get_credentials(user_id)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to retrieve Immich credentials for avatar proxy",
                user_id=user_id,
            )
            return None, None

    @staticmethod
    async def _fetch_thumbnail(
        server_url: str, api_key: str, person_id: str
    ) -> tuple[bytes, str]:
        """Download the person thumbnail from Immich.

        Returns:
            Tuple of (image bytes, content-type).

        Raises:
            AvatarNotFoundError: If the Immich API returns an error.
        """
        # Validate the server URL to prevent SSRF
        parsed = urlparse(server_url)
        if parsed.scheme not in ("http", "https"):
            raise AvatarNotFoundError(
                f"Invalid Immich server URL scheme: {parsed.scheme}"
            )

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
                content_type = response.headers.get("content-type", "image/jpeg")
                return response.content, content_type
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
