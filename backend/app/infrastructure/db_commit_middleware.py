"""
Commit-before-response backstop middleware.

The request-scoped DB connection runs in commit-as-you-go mode (see
``app.infrastructure.di.database``). Endpoints migrated to explicit
service-layer transactions commit themselves (mid-handler, before the
response). This middleware is a **temporary safety net** for write endpoints
that have not yet been migrated: it commits the request connection on a
successful write response *before the response bytes are sent*, so those writes
are durable and visible to an immediate follow-up request (fixing the
read-after-write race from issue #945 universally, not just for migrated
endpoints).

As endpoints are converted to service-layer ``unit_of_work``/``@transactional``
units, they stop relying on this backstop; once every write path is migrated
this middleware can be removed.

It only ever settles a connection the request actually opened: the connection
provider publishes the live connection via the ``request_connection`` ContextVar
when it creates one, and this middleware reads that. A request that never
touched the DB (or failed validation before the handler) has no connection, so
nothing is created or committed here — a DB outage can't turn a non-DB request
into a 5xx, and invalid traffic doesn't cause spurious connection checkouts.

Committing happens before forwarding ``http.response.start``; if the commit
fails, the error propagates and becomes a 5xx instead of a false success.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.infrastructure.unit_of_work import (
    in_external_transaction,
    request_connection,
)

# Reads never write, so never need a commit.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class CommitOnResponseMiddleware:
    """Commit the request DB transaction before a successful write response."""

    def __init__(self, app: ASGIApp, *, skip_path_prefix: str | None = None) -> None:
        self.app = app
        # Requests under this prefix (the mounted MCP sub-app) manage their own
        # commit timing (service-layer units + the provider teardown net), so
        # skip them here.
        self.skip_path_prefix = skip_path_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "GET") in _SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        if self.skip_path_prefix and scope.get("path", "").startswith(
            self.skip_path_prefix
        ):
            await self.app(scope, receive, send)
            return

        settled = False

        async def send_wrapper(message: Message) -> None:
            nonlocal settled
            if message["type"] == "http.response.start" and not settled:
                settled = True
                # Settle the request transaction before the response is sent:
                # commit on success, roll back on a 4xx/5xx (the handler failed
                # or rejected the request — don't persist its writes, and don't
                # leave them for the connection-provider teardown to commit).
                await self._settle(success=message["status"] < 400)
            await send(message)

        await self.app(scope, receive, send_wrapper)

    async def _settle(self, *, success: bool) -> None:
        connection = request_connection.get()
        if connection is None:
            # The request never opened a DB connection — nothing to settle.
            return
        # Under the integration test fixture the connection is a shared,
        # test-owned transaction; committing/rolling it back would break
        # isolation. Writes are already visible on that connection within the
        # test, so leave it untouched.
        if in_external_transaction(connection):
            return
        if not connection.in_transaction():
            return
        if success:
            await connection.commit()
        else:
            await connection.rollback()
