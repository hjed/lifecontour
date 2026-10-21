"""Re-import every Google contact when something the import reads changes.

The Google import fills in addresses with no country from the user's default
country (#1820). The worker skips a person whose etag has not moved, so a new
default would only reach a contact the next time it changed in Google; a full
sync re-applies every person (``force_apply``) and so reaches them all.
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.exceptions import JobEnqueueError
from app.core.integrations.task_queue_service import TaskQueueService
from app.infrastructure.auth.oauth_service import OAuthService

logger = structlog.get_logger()


class GoogleContactsResync:
    """Queue a full Google contacts sync for a user, when Google is connected."""

    def __init__(
        self, oauth_service: OAuthService, task_queue_service: TaskQueueService
    ) -> None:
        self.oauth_service = oauth_service
        self.task_queue_service = task_queue_service

    async def request_full_sync(
        self, user_id: str, connection: AsyncConnection
    ) -> None:
        """Queue the sync; best-effort, so a failure is logged, never raised.

        The periodic sync picks the change up later if the queue is down, and a
        user without exactly one connected Google account has nothing to sync.
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
            await self.task_queue_service.enqueue_google_sync(
                google_account_email=google_account_email,
                user_id=user_id,
                sync_type="full",
            )
        except (JobEnqueueError, ConnectionError) as e:
            logger.warning(
                "Could not queue a full Google contacts sync",
                user_id=user_id,
                error=str(e),
            )
