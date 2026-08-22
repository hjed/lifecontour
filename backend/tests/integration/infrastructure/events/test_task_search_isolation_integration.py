"""Tasks are not indexed, end to end.

The home-dashboard specification, §*Tasks and search*:

    Tasks are **not** indexed and do not appear in global search. There is no
    tasks index, and a global search never returns a task. The search indexer
    should ignore task events rather than failing on them.

    This follows from the no-accumulating-backlog principle: a searchable task
    corpus is a backlog by another name.

That is true by construction twice over — no task type is in the
``search-indexer`` group's pattern list, and ``SearchIndexer.process_event``
branches on ``Contact``/``Journal`` and skips everything else — and the unit
tests pin both halves. What they cannot show is the *whole* chain: that a real
task lifecycle, relayed onto the same stream the indexer reads, leaves the
indexer having done nothing, with nothing pending, nothing dead-lettered, no
index created, and nothing findable.

The events are produced by driving ``TaskService`` rather than published by
hand, because a hand-written event proves only that the string does not match.
The point is that the writes a *user* performs never reach MeiliSearch.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskStatus
from core_shared.stream_client import StreamClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.infrastructure.events.outbox_relay import OutboxRelay
from app.infrastructure.events.search_indexer_consumer import SearchIndexerConsumer
from app.infrastructure.search.meilisearch_client import (
    get_index_name,
    get_meilisearch_client,
)
from app.infrastructure.search.search_indexer import SearchIndexer
from app.infrastructure.search.search_service import SearchService
from tests.integration.tasks.task_seeding import (
    USER_ID,
    create_contact,
    create_journal,
    service_on,
    task_events,
)
from tests.task_event_inventory import task_event_types

GROUP_NAME = "search-indexer"

# The text of the task each scenario drives. Only the global-search test needs a
# distinctive one, and it builds its own.
TASK_TEXT = "Book the venue"

# What ``_every_kind_of_task_write`` below has to reach. Spelt out rather than
# taken from the shared inventory, because the inventory is every type the
# *domain* defines and a task's anchors are also re-pointed by the journal
# domain — an event no ``TaskService`` call can produce. Deriving this from the
# inventory would make these search tests fail, with messages about indexing, on
# the day that type is added.
_TYPES_A_TASK_SERVICE_WRITE_PUBLISHES = {
    "TaskCreated",
    "TaskUpdated",
    "TaskDueJournalRetargeted",
    "TaskJournalLinked",
    "TaskJournalUnlinked",
    "TaskDeleted",
}


@pytest.fixture
def meilisearch_pointed_at_the_test_server(test_settings: Any) -> Iterator[None]:
    """Point the cached MeiliSearch client at this workspace's test container.

    ``get_meilisearch_client`` is an ``lru_cache`` over ``get_settings()``, which
    resolves the *application's* URL — port 7700 — while the test server runs on
    the workspace-derived port. Patching the settings the factory reads and
    clearing the cache either side is what makes ``SearchService`` and
    ``SearchIndexer`` talk to the container the rest of the suite uses.
    """
    get_meilisearch_client.cache_clear()
    with patch(
        "app.infrastructure.search.meilisearch_client.get_settings",
        return_value=test_settings,
    ):
        yield
    get_meilisearch_client.cache_clear()


async def _every_kind_of_task_write(conn: AsyncConnection, text_value: str) -> int:
    """Drive one task through every write path the domain has, and return its id.

    Every event type this domain's service publishes ends up on the stream —
    create, update, the retarget's pair, a manual attach and detach, and the
    delete — so the assertions below are about the whole vocabulary rather than
    whichever type happened to be published.
    """
    service = service_on(conn, SqlUserSettingsRepository(conn))
    journal_repo = SqlJournalRepository(conn)
    creating_journal_id = await create_journal(journal_repo, title="Today")
    due_journal_id = await create_journal(
        journal_repo, title="Next week", days_offset=7
    )
    new_due_journal_id = await create_journal(
        journal_repo, title="The week after", days_offset=14
    )
    mentioned_journal_id = await create_journal(
        journal_repo, title="Mentioned", days_offset=3
    )

    task = await service.create_task(
        user_id=USER_ID,
        creating_journal_id=creating_journal_id,
        due_journal_id=due_journal_id,
        text=text_value,
        transaction=conn,
        source=Provenance.UI,
        changed_by="ui",
    )
    assert task.id is not None
    await service.set_status(
        user_id=USER_ID,
        task_id=task.id,
        status=TaskStatus.DONE,
        transaction=conn,
        source=Provenance.UI,
        changed_by="ui",
    )
    await service.retarget_due_journal(
        user_id=USER_ID,
        task_id=task.id,
        due_journal_id=new_due_journal_id,
        transaction=conn,
        acknowledge_reopen=True,
        source=Provenance.UI,
        changed_by="ui",
    )
    assert await service.attach_intermediate_journal(
        user_id=USER_ID,
        task_id=task.id,
        journal_id=mentioned_journal_id,
        transaction=conn,
        source=Provenance.UI,
        changed_by="ui",
    )
    assert await service.detach_intermediate_journal(
        user_id=USER_ID,
        task_id=task.id,
        journal_id=mentioned_journal_id,
        transaction=conn,
        source=Provenance.UI,
        changed_by="ui",
    )
    await service.delete_task(
        user_id=USER_ID,
        task_id=task.id,
        transaction=conn,
        source=Provenance.UI,
        changed_by="ui",
    )

    published = {event.event_type for event in await task_events(conn)}
    assert published <= task_event_types(), (
        f"published a type the events module does not define: "
        f"{sorted(published - task_event_types())}"
    )
    assert published >= _TYPES_A_TASK_SERVICE_WRITE_PUBLISHES, (
        "This helper is only worth anything if it drives every write path; "
        f"missing {sorted(_TYPES_A_TASK_SERVICE_WRITE_PUBLISHES - published)}"
    )
    return task.id


async def _index_a_contact(
    conn: AsyncConnection, stream_client: StreamClient, stream_name: str, name: str
) -> None:
    """Put a real contact on the stream alongside the task events.

    The positive control. Without it every assertion below is satisfied by an
    indexer that does nothing at all — a broken client, a misconfigured URL, a
    consumer that read no messages — and "no task was indexed" would be true for
    the wrong reason. A contact travelling the same batch means the indexer
    demonstrably worked in the very run that indexed no task.
    """
    contact_id = await create_contact(conn, first_name=name)
    await stream_client.publish(
        stream_name=stream_name,
        event_id=f"evt-{uuid.uuid4().hex[:8]}",
        event_type="ContactCreated",
        aggregate_id=contact_id,
        event_data={"contact_id": contact_id},
        occurred_at="2024-01-01T12:00:00Z",
    )


async def _index_a_journal(
    conn: AsyncConnection, stream_client: StreamClient, stream_name: str, title: str
) -> None:
    """The same control for the journals index, which is created just as lazily."""
    journal_id = await create_journal(SqlJournalRepository(conn), title=title)
    await stream_client.publish(
        stream_name=stream_name,
        event_id=f"evt-{uuid.uuid4().hex[:8]}",
        event_type="JournalCreated",
        aggregate_id=journal_id,
        event_data={"journal_id": journal_id},
        occurred_at="2024-01-01T12:00:00Z",
    )


@dataclass
class IndexerCalls:
    """What the real indexer was handed, and what came back out alive.

    ``_process_batch`` returns the number of messages *read*, which counts a
    matched event whose handler raised — so the count alone cannot say the
    control worked. These two lists can: ``indexed`` records the events that
    returned from the real ``SearchIndexer`` without raising.
    """

    indexed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def _recording_indexer(calls: IndexerCalls) -> Any:
    """A factory for the **real** indexer that records how each event ended.

    Not a stub: the instance is a genuine ``SearchIndexer`` doing genuine
    MeiliSearch work, with one wrapper around ``process_event``. A double would
    defeat the purpose — the point is that the control document really was
    indexed, in this run, by the code under test.
    """

    def make(*args: Any, **kwargs: Any) -> SearchIndexer:
        indexer = SearchIndexer(*args, **kwargs)
        original = indexer.process_event

        async def process_event(event: Any) -> None:
            try:
                await original(event)
            except Exception:
                calls.failed.append(event.event_type)
                raise
            calls.indexed.append(event.event_type)

        indexer.process_event = process_event  # type: ignore[method-assign]
        return indexer

    return make


async def _run_search_indexer(
    stream_client: StreamClient,
    stream_name: str,
    conn: AsyncConnection,
    name: str,
    *,
    dead_letter_on_first_retry: bool = False,
    indexer_factory: Any | None = None,
) -> int:
    """Relay the outbox and run one batch of the real ``search-indexer`` group.

    The consumer's engine is patched to the test connection so its reads see the
    rows this test wrote inside the savepoint, exactly as the projection harness
    does for the history consumer.

    ``batch_size`` matches the relay's rather than taking the consumer's default
    of 10. A lifecycle here publishes seven events and the controls two more, so
    the default would start silently leaving messages unread the moment this
    domain gains another event type — dropping the *controls* first, since they
    are published last, which is precisely the rot they exist to catch.

    ``dead_letter_on_first_retry`` claims pending entries immediately and treats
    one failed delivery as terminal, which is the only way a single-batch test can
    reach the dead-letter path at all.

    ``indexer_factory`` replaces the ``SearchIndexer`` the consumer constructs —
    with a recorder around the real one, or with something that fails on purpose.
    """
    relay = OutboxRelay(
        stream_client=stream_client, stream_name=stream_name, batch_size=50
    )
    await relay.relay_batch(conn)

    consumer = SearchIndexerConsumer(
        stream_client=stream_client,
        stream_name=stream_name,
        consumer_name=name,
        batch_size=50,
        block_ms=100,
    )
    if dead_letter_on_first_retry:
        consumer._retry_min_idle_ms = 0
        consumer._max_delivery_count = 1
    await stream_client.ensure_consumer_group(stream_name, GROUP_NAME)

    mock_engine = MagicMock()

    @asynccontextmanager
    async def mock_begin() -> AsyncIterator[AsyncConnection]:
        yield conn

    mock_engine.begin = mock_begin

    patches = [
        patch(
            "app.infrastructure.events.search_indexer_consumer.get_async_database_engine",
            return_value=mock_engine,
        ),
        patch(
            "app.infrastructure.events.dead_letter_consumer_mixin.get_async_database_engine",
            return_value=mock_engine,
        ),
    ]
    if indexer_factory is not None:
        patches.append(
            patch(
                "app.infrastructure.events.search_indexer_consumer.SearchIndexer",
                side_effect=indexer_factory,
            )
        )

    with ExitStack() as stack:
        for entered in patches:
            stack.enter_context(entered)
        processed = await consumer._process_batch()
        if dead_letter_on_first_retry:
            await consumer._retry_pending()
        return processed


@pytest.mark.integration
class TestTasksNeverReachTheSearchIndexer:
    @pytest.mark.asyncio
    async def test_the_group_consumes_task_events_without_indexing_anything(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """*"Ignore rather than fail"* — the spec's own wording — with nothing left over.

        The batch is read (so the events genuinely reached this group and were not
        filtered out somewhere upstream), ``SearchIndexer`` is never constructed,
        and every entry is acknowledged. An unacknowledged entry would sit pending
        until it was reclaimed and eventually dead-lettered, which is the failure
        mode "ignores" is meant to exclude.
        """
        await _every_kind_of_task_write(async_connection, TASK_TEXT)

        with patch(
            "app.infrastructure.events.search_indexer_consumer.SearchIndexer"
        ) as mock_indexer:
            count = await _run_search_indexer(
                stream_client, test_stream_name, async_connection, "test-search-tasks"
            )

        # Counted from what the lifecycle actually published rather than from the
        # inventory: an event type published by *another* domain's write path
        # belongs to that domain's completeness test, not to this arithmetic.
        assert count == len(await task_events(async_connection))
        mock_indexer.assert_not_called()

        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

    @pytest.mark.asyncio
    async def test_no_task_event_dead_letters_while_a_failing_event_does(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """The other half of "ignore rather than fail", with a live control.

        Dead-lettering is only reachable from ``_retry_pending``, and only for an
        entry that failed and stayed pending long enough to be redelivered
        ``max_delivery_count`` times. A task event can never get there: it is
        unmatched, so the first batch acknowledges it and it is never pending —
        which means *"no task event dead-letters"* is true of a consumer that
        raises on every task event too, and asserting an empty table alone proves
        nothing at all.

        So the indexer is made to fail on everything it is handed. The contact
        event is matched, fails, stays pending and dead-letters; the task events
        are never handed to it and never appear. The control is the whole test:
        the same machinery, in the same run, demonstrably capable of writing the
        row that the task events do not write.
        """
        await _every_kind_of_task_write(async_connection, TASK_TEXT)
        await _index_a_contact(
            async_connection, stream_client, test_stream_name, "DeadLetterControl"
        )

        failing_indexer = MagicMock()
        failing_indexer.process_event = AsyncMock(
            side_effect=RuntimeError("indexing is broken")
        )

        with patch(
            "app.infrastructure.events.search_indexer_consumer.SearchIndexer",
            return_value=failing_indexer,
        ):
            await _run_search_indexer(
                stream_client,
                test_stream_name,
                async_connection,
                "test-search-deadletter",
                dead_letter_on_first_retry=True,
            )

        dead_lettered = await async_connection.execute(
            text(
                "SELECT event_type FROM dead_letter_events WHERE consumer_group = :group"
            ),
            {"group": GROUP_NAME},
        )
        types = {row.event_type for row in dead_lettered}

        # The control landed, so the path is live in this run...
        assert types == {"ContactCreated"}
        # ...and not one task event took it.
        assert not types & task_event_types()

        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

    @pytest.mark.asyncio
    async def test_no_tasks_index_is_created(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        meilisearch_pointed_at_the_test_server: None,
    ) -> None:
        """*"There is no tasks index"*, checked against MeiliSearch itself.

        Indexes are created lazily by the indexer on its first event of a kind,
        so "no index appears" is a claim about what the indexer does rather than
        about a static configuration — which is why it is worth asking the server.

        The contact travelling the same batch is the control, and what makes it
        one is that the **real** indexer is recorded returning from it. Neither
        weaker form would do: MeiliSearch is not rolled back between tests and its
        indexes carry a fixed per-workspace prefix, so the contacts index existing
        proves only that some earlier test created it — and ``_process_batch``
        counts a matched event whose handler *raised*, so the message count does
        not prove the contact path worked either. ``calls.indexed`` does.
        """
        await _every_kind_of_task_write(async_connection, TASK_TEXT)
        await _index_a_contact(
            async_connection, stream_client, test_stream_name, "IndexControl"
        )

        calls = IndexerCalls()
        consumed = await _run_search_indexer(
            stream_client,
            test_stream_name,
            async_connection,
            "test-search-index",
            indexer_factory=_recording_indexer(calls),
        )

        # Every message was read, the contact was indexed without raising, and
        # the indexer was handed nothing else at all.
        assert consumed == len(await task_events(async_connection)) + 1
        assert calls.indexed == ["ContactCreated"]
        assert calls.failed == []

        client = get_meilisearch_client()
        index_names = {index.uid for index in client.get_indexes()["results"]}
        assert get_index_name("contacts") in index_names
        assert get_index_name("tasks") not in index_names
        assert not [uid for uid in index_names if uid.endswith("tasks")]

    @pytest.mark.asyncio
    async def test_a_global_search_never_returns_a_task(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        meilisearch_pointed_at_the_test_server: None,
    ) -> None:
        """The user-facing statement, asserted the way a user would meet it.

        The search surface is exactly two indexes — ``search_contacts`` and
        ``search_journals`` are the only queries ``SearchService`` offers — so a
        task can appear only by being written into one of them. Both are asked
        for the task's text, which is unique to this run so a hit could not be a
        coincidence of an index shared with other tests.

        A contact and a journal ride the same batch, carrying no part of the
        task's text. They are what make an empty result mean something: both were
        indexed by the real indexer in this run without raising, so "nothing
        found" is the search working rather than the search erroring or the
        indexer never having got there.

        The control is *"the write succeeded"*, not *"the document is
        searchable"*. MeiliSearch writes are asynchronous, so asserting a freshly
        indexed document comes back from a query would trade a real guarantee for
        a race.
        """
        run_token = uuid.uuid4().hex[:12]
        task_text = f"Zarquon{run_token} venue"
        await _every_kind_of_task_write(async_connection, task_text)
        await _index_a_contact(
            async_connection, stream_client, test_stream_name, "SearchControl"
        )
        await _index_a_journal(
            async_connection, stream_client, test_stream_name, "Search control journal"
        )

        calls = IndexerCalls()
        await _run_search_indexer(
            stream_client,
            test_stream_name,
            async_connection,
            "test-search-global",
            indexer_factory=_recording_indexer(calls),
        )
        assert sorted(calls.indexed) == ["ContactCreated", "JournalCreated"]
        assert calls.failed == []

        index_names = {
            index.uid for index in get_meilisearch_client().get_indexes()["results"]
        }
        assert {get_index_name("contacts"), get_index_name("journals")} <= index_names

        search_service = SearchService()
        for query in (task_text, f"Zarquon{run_token}", run_token):
            assert search_service.search_contacts(query=query)["hits"] == []
            assert search_service.search_journals(query=query)["hits"] == []
