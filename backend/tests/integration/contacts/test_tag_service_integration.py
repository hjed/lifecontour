"""Integration tests for TagService against a real database.

Covers the create-or-get race-safety of ``create_tag`` (a duplicate-name insert
must roll back via its SAVEPOINT, without poisoning the surrounding unit of work,
and fall back to the existing tag), and the path-change events a tag's
descendants get when it is renamed, moved, deleted or merged.
"""

import json
from collections.abc import Sequence

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import SqlContactEventPublisher, SqlTagRepository
from app.core.contacts.models.repositories import (
    ContactEventPublisher,
    DomainEventProtocol,
)
from app.core.contacts.services.tag_hierarchy_service import TagHierarchyService
from app.core.contacts.services.tag_service import TagService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.contact_seeding import TEST_USER_ID


@pytest.mark.integration
class TestTagServiceCreateOrGetIntegration:
    """create_tag is a race-safe create-or-get against real Postgres."""

    @pytest.fixture
    def tag_repo(self, clean_database: AsyncConnection):
        return SqlTagRepository(clean_database)

    @pytest.fixture
    def service(self, tag_repo, clean_database):
        return TagService(
            tag_repo=tag_repo,
            tag_hierarchy_service=TagHierarchyService(tag_repo),
            event_publisher=SqlContactEventPublisher(clean_database),
        )

    @pytest.mark.asyncio
    async def test_create_tag_returns_existing_on_duplicate_name(
        self, service, clean_database
    ):
        """A second create of the same name returns the first tag, not an error.

        This exercises the real SAVEPOINT recovery: the duplicate INSERT raises a
        unique-violation that, without the savepoint, would abort the whole
        transaction. The savepoint rolls back just the failed insert so the
        service can look the existing tag up and return it.
        """
        first = await service.create_tag(
            name="Work", transaction=clean_database, user_id=TEST_USER_ID
        )
        assert first.id is not None

        second = await service.create_tag(
            name="Work", transaction=clean_database, user_id=TEST_USER_ID
        )

        # Same row returned, no DuplicateTagNameError surfaced to the caller.
        assert second.id == first.id

        # Case-insensitive match: the constraint is on LOWER(name).
        third = await service.create_tag(
            name="WORK", transaction=clean_database, user_id=TEST_USER_ID
        )
        assert third.id == first.id

    @pytest.mark.asyncio
    async def test_connection_usable_after_duplicate_recovery(
        self, service, clean_database
    ):
        """After a duplicate is recovered, the connection still accepts writes.

        Proves the unit of work was not poisoned by the failed insert: a
        subsequent, unrelated create succeeds on the same connection.
        """
        await service.create_tag(
            name="Work", transaction=clean_database, user_id=TEST_USER_ID
        )
        await service.create_tag(
            name="Work", transaction=clean_database, user_id=TEST_USER_ID
        )  # duplicate

        other = await service.create_tag(
            name="Personal", transaction=clean_database, user_id=TEST_USER_ID
        )
        assert other.id is not None

        repo = SqlTagRepository(clean_database)
        assert (await repo.find_by_name("Work", user_id=TEST_USER_ID)) is not None
        assert (await repo.find_by_name("Personal", user_id=TEST_USER_ID)) is not None


class CapturingEventPublisher(ContactEventPublisher):
    """Collects published events so a test can assert on them directly."""

    def __init__(self) -> None:
        self.events: list[DomainEventProtocol] = []

    async def publish(self, event: DomainEventProtocol) -> None:
        self.events.append(event)

    async def publish_batch(self, events: Sequence[DomainEventProtocol]) -> None:
        self.events.extend(events)


def _path_changes(events: list[DomainEventProtocol]) -> dict[int, tuple[str, str]]:
    """Each TagUpdated event's ``full_path`` change, by tag id."""
    return {
        event.event_data["tag_id"]: tuple(
            event.event_data["changed_fields"]["full_path"]
        )
        for event in events
        if event.event_type == "TagUpdated"
        and "full_path" in event.event_data["changed_fields"]
    }


@pytest.mark.integration
class TestTagServiceDescendantPathEvents:
    """A tag's path change reaches its descendants as their own events (#1836).

    Only the Google worker reads these: it renames each descendant's contact
    group by its old path, which nothing else would tell it had changed.

    The tree's names sort before their parents (``Apple`` under ``Yarn`` under
    ``Zeta``), as the descendant query orders by name rather than depth.
    """

    @pytest.fixture
    def publisher(self) -> CapturingEventPublisher:
        return CapturingEventPublisher()

    @pytest.fixture
    def service(
        self, clean_database: AsyncConnection, publisher: CapturingEventPublisher
    ) -> TagService:
        tag_repo = SqlTagRepository(clean_database)
        return TagService(
            tag_repo=tag_repo,
            tag_hierarchy_service=TagHierarchyService(tag_repo),
            event_publisher=publisher,
        )

    @pytest.fixture
    async def tree(
        self,
        service: TagService,
        clean_database: AsyncConnection,
        publisher: CapturingEventPublisher,
    ) -> dict[str, int]:
        """``Zeta → Yarn → Apple``, ``Zeta → Bee``, and an unrelated ``Work``."""
        ids: dict[str, int] = {}
        for name, parent in (
            ("Zeta", None),
            ("Yarn", "Zeta"),
            ("Apple", "Yarn"),
            ("Bee", "Zeta"),
            ("Work", None),
        ):
            tag = await service.create_tag(
                name=name,
                parent_id=ids[parent] if parent else None,
                transaction=clean_database,
                user_id=TEST_USER_ID,
            )
            assert tag.id is not None
            ids[name] = tag.id
        publisher.events.clear()
        return ids

    @pytest.mark.asyncio
    async def test_rename_publishes_every_descendant_path(
        self,
        service: TagService,
        clean_database: AsyncConnection,
        publisher: CapturingEventPublisher,
        tree: dict[str, int],
    ) -> None:
        await service.update_tag(
            tree["Zeta"], clean_database, name="Kin", user_id=TEST_USER_ID
        )

        assert _path_changes(publisher.events) == {
            tree["Zeta"]: ("Zeta", "Kin"),
            tree["Yarn"]: ("Zeta/Yarn", "Kin/Yarn"),
            tree["Apple"]: ("Zeta/Yarn/Apple", "Kin/Yarn/Apple"),
            tree["Bee"]: ("Zeta/Bee", "Kin/Bee"),
        }
        descendant_events = [
            e for e in publisher.events if e.event_data["tag_id"] == tree["Apple"]
        ]
        assert len(descendant_events) == 1
        assert descendant_events[0].event_data["tag_name"] == "Kin/Yarn/Apple"
        assert descendant_events[0].event_data["user_id"] == TEST_USER_ID
        assert descendant_events[0].aggregate_id == tree["Apple"]

    @pytest.mark.asyncio
    async def test_move_publishes_descendant_paths_both_ways(
        self,
        service: TagService,
        clean_database: AsyncConnection,
        publisher: CapturingEventPublisher,
        tree: dict[str, int],
    ) -> None:
        await service.update_tag(
            tree["Yarn"], clean_database, parent_id=tree["Work"], user_id=TEST_USER_ID
        )
        assert _path_changes(publisher.events) == {
            tree["Yarn"]: ("Zeta/Yarn", "Work/Yarn"),
            tree["Apple"]: ("Zeta/Yarn/Apple", "Work/Yarn/Apple"),
        }

        publisher.events.clear()
        await service.update_tag(
            tree["Yarn"], clean_database, set_parent_null=True, user_id=TEST_USER_ID
        )
        assert _path_changes(publisher.events) == {
            tree["Yarn"]: ("Work/Yarn", "Yarn"),
            tree["Apple"]: ("Work/Yarn/Apple", "Yarn/Apple"),
        }

    @pytest.mark.asyncio
    async def test_update_without_a_path_change_publishes_no_descendant_events(
        self,
        service: TagService,
        clean_database: AsyncConnection,
        publisher: CapturingEventPublisher,
        tree: dict[str, int],
    ) -> None:
        await service.update_tag(
            tree["Zeta"], clean_database, color="#ff0000", user_id=TEST_USER_ID
        )

        assert [e.event_data["tag_id"] for e in publisher.events] == [tree["Zeta"]]
        assert _path_changes(publisher.events) == {}

    @pytest.mark.asyncio
    async def test_delete_publishes_descendants_rerooted(
        self,
        service: TagService,
        clean_database: AsyncConnection,
        publisher: CapturingEventPublisher,
        tree: dict[str, int],
    ) -> None:
        await service.delete_tag(tree["Zeta"], clean_database, user_id=TEST_USER_ID)

        deleted = [e for e in publisher.events if e.event_type == "TagDeleted"]
        assert [e.event_data["tag_name"] for e in deleted] == ["Zeta"]
        assert _path_changes(publisher.events) == {
            tree["Yarn"]: ("Zeta/Yarn", "Yarn"),
            tree["Apple"]: ("Zeta/Yarn/Apple", "Yarn/Apple"),
            tree["Bee"]: ("Zeta/Bee", "Bee"),
        }

    @pytest.mark.asyncio
    async def test_merge_publishes_descendants_under_the_target(
        self,
        service: TagService,
        clean_database: AsyncConnection,
        publisher: CapturingEventPublisher,
        tree: dict[str, int],
    ) -> None:
        await service.merge_tags(
            tree["Zeta"], tree["Work"], clean_database, user_id=TEST_USER_ID
        )

        deleted = [e for e in publisher.events if e.event_type == "TagDeleted"]
        assert [e.event_data["tag_name"] for e in deleted] == ["Zeta"]
        assert _path_changes(publisher.events) == {
            tree["Yarn"]: ("Zeta/Yarn", "Work/Yarn"),
            tree["Apple"]: ("Zeta/Yarn/Apple", "Work/Yarn/Apple"),
            tree["Bee"]: ("Zeta/Bee", "Work/Bee"),
        }

    @pytest.mark.asyncio
    async def test_merge_into_an_ancestor_lifts_descendants(
        self,
        service: TagService,
        clean_database: AsyncConnection,
        publisher: CapturingEventPublisher,
        tree: dict[str, int],
    ) -> None:
        await service.merge_tags(
            tree["Yarn"], tree["Zeta"], clean_database, user_id=TEST_USER_ID
        )

        assert _path_changes(publisher.events) == {
            tree["Apple"]: ("Zeta/Yarn/Apple", "Zeta/Apple"),
        }

    @pytest.mark.asyncio
    async def test_merge_of_a_childless_tag_publishes_only_the_delete(
        self,
        service: TagService,
        clean_database: AsyncConnection,
        publisher: CapturingEventPublisher,
        tree: dict[str, int],
    ) -> None:
        await service.merge_tags(
            tree["Bee"], tree["Work"], clean_database, user_id=TEST_USER_ID
        )

        assert [(e.event_type, e.event_data["tag_name"]) for e in publisher.events] == [
            ("TagDeleted", "Zeta/Bee")
        ]

    @pytest.mark.asyncio
    async def test_descendant_path_change_reaches_the_outbox(
        self,
        clean_database: AsyncConnection,
        service: TagService,
        tree: dict[str, int],
    ) -> None:
        """The JSON payload carries the old/new pair the Google worker unpacks."""
        tag_repo = SqlTagRepository(clean_database)
        outbox_service = TagService(
            tag_repo=tag_repo,
            tag_hierarchy_service=TagHierarchyService(tag_repo),
            event_publisher=OutboxEventPublisher(clean_database),
        )

        await outbox_service.update_tag(
            tree["Zeta"], clean_database, name="Kin", user_id=TEST_USER_ID
        )

        row = (
            await clean_database.execute(
                text(
                    "SELECT event_data FROM outbox_events "
                    "WHERE event_type = 'TagUpdated' AND aggregate_id = :tag_id"
                ),
                {"tag_id": tree["Apple"]},
            )
        ).one()
        event_data = json.loads(row.event_data)
        old_path, new_path = event_data["changed_fields"]["full_path"]
        assert (old_path, new_path) == ("Zeta/Yarn/Apple", "Kin/Yarn/Apple")
        assert event_data["user_id"] == TEST_USER_ID
