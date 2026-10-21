"""Run the Google contacts sync now, when something the import reads changed.

Saving the default country clears the user's contacts sync token (#1820), so
whichever sync runs next is a full one; this queues that sync straight away
rather than waiting for the next periodic run (which may be switched off).
"""

from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.task_queue_service import TaskQueueService
from app.infrastructure.auth.oauth_service import OAuthService

logger = structlog.get_logger()


class GoogleContactsResync:
    """Queue a Google contacts sync for a user, when Google is connected."""

    def __init__(
        self,
        oauth_service: OAuthService,
        task_queue_service: Callable[[], Awaitable[TaskQueueService]],
    ) -> None:
        """``task_queue_service`` is resolved only when needed: building it
        connects to Redis, which must never be what fails a settings save."""
        self.oauth_service = oauth_service
        self.task_queue_service = task_queue_service

    async def request_sync(self, user_id: str, connection: AsyncConnection) -> None:
        """Queue the sync; best-effort, so any failure is logged, never raised.

        The cleared token still makes the next sync a full one, and a user
        without exactly one connected Google account has nothing to sync.
        """
        try:
            google_account_email = (
                await self.oauth_service.get_connected_google_account_email(
                    user_id, connection
                )
            )
        except ValueError:
            return
        try:
            task_queue = await self.task_queue_service()
            await task_queue.enqueue_google_sync(
                google_account_email=google_account_email,
                user_id=user_id,
                sync_type="smart",
            )
        except Exception as e:  # noqa: BLE001 - best-effort; the token is cleared
            logger.warning(
                "Could not queue a Google contacts sync",
                user_id=user_id,
                error=str(e),
            )
