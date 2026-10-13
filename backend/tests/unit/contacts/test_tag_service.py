"""Unit tests for tag mutation service."""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.contacts.entities import Tag
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.contacts.value_objects import TagName

from app.core.contacts.models.events import TagDeleted, TagUpdated
from app.core.contacts.models.exceptions import DuplicateTagNameError, TagNotFoundError
from app.core.contacts.services.tag_service import TagService

OWNER = "tag-owner"


class DummyTagHierarchyService:
    def __init__(self):
        self.throw_uniqueness = False
        self.throw_cycle = False

    async def validate_tag_name_uniqueness(
        self, name: str, _transaction, exclude_tag_id=None, *, user_id
    ):
        if self.throw_uniqueness:
            raise DuplicateTagNameError(name)

    async def validate_parent_child_relationship(
        self, parent_id, child_id, transaction, *, user_id
    ):
        if self.throw_cycle:
            raise ContactValidationError("parent_id", "cycle detected")

    async def get_tag_path(self, tag_id: int, *, user_id: str):
        # Just return empty list or a dummy list for testing since it uses str(tag.name) if empty
        return []


class MockTagRepository:
    def __init__(self):
        self.tags: dict[int, Tag] = {}
        self.deleted_ids = set()
        # When set, the next save() raises DuplicateTagNameError (simulating the
        # DB unique-name constraint firing on a concurrent create).
        self.raise_duplicate_on_save = False

    async def find_by_id(self, tag_id: int, *, user_id: str) -> Tag | None:
        tag = self.tags.get(tag_id)
        if tag_id in self.deleted_ids or tag is None or tag.user_id != user_id:
            return None
        return tag

    async def find_by_name(self, name: str, *, user_id: str) -> Tag | None:
        for tag in self.tags.values():
            if str(tag.name).lower() == name.lower() and tag.user_id == user_id:
                return tag
        return None

    async def save(self, tag: Tag, *, user_id: str) -> Tag:
        if self.raise_duplicate_on_save:
            raise DuplicateTagNameError(str(tag.name))
        if tag.id is None:
            tag.id = len(self.tags) + 1
            tag.user_id = user_id
        assert tag.id is not None
        self.tags[tag.id] = tag
        return tag

    async def delete(self, tag_id: int) -> None:
        self.deleted_ids.add(tag_id)
        if tag_id in self.tags:
            del self.tags[tag_id]


class MockEventPublisher:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


@pytest.fixture
def repo():
    return MockTagRepository()


@pytest.fixture
def hierarchy_service():
    return DummyTagHierarchyService()


@pytest.fixture
def publisher():
    return MockEventPublisher()


@pytest.fixture
def service(repo, hierarchy_service, publisher):
    return TagService(
        tag_repo=repo,
        tag_hierarchy_service=hierarchy_service,
        event_publisher=publisher,
    )


@pytest.mark.asyncio
async def test_create_tag_persists_and_returns(service, repo):
    created = await service.create_tag(
        name="New_Tag",
        transaction=None,
        color="#123456",
        description="desc",
        user_id=OWNER,
    )

    assert created.id is not None
    assert str(created.name) == "New_Tag"
    assert created.color == "#123456"
    assert created.description == "desc"
    assert repo.tags[created.id] is created


@pytest.mark.asyncio
async def test_create_tag_with_existing_parent(service, repo):
    parent = Tag(id=1, name=TagName("Parent"), user_id=OWNER)
    await repo.save(parent, user_id=OWNER)

    created = await service.create_tag(
        name="Child", transaction=None, parent_id=1, user_id=OWNER
    )

    assert created.parent_id == 1


@pytest.mark.asyncio
async def test_create_tag_missing_parent_raises(service):
    with pytest.raises(TagNotFoundError):
        await service.create_tag(
            name="Orphan", transaction=None, parent_id=99, user_id=OWNER
        )


@pytest.mark.asyncio
async def test_create_tag_returns_existing_on_duplicate_name_race(service, repo):
    """A lost create-or-get race returns the winner's tag instead of erroring."""
    # The winner already created the tag.
    winner = Tag(id=7, name=TagName("Work"), user_id=OWNER)
    await repo.save(winner, user_id=OWNER)
    # Our insert loses the race: the unique-name constraint fires.
    repo.raise_duplicate_on_save = True

    result = await service.create_tag(name="Work", transaction=None, user_id=OWNER)

    assert result is winner


@pytest.mark.asyncio
async def test_create_tag_reraises_duplicate_when_no_existing(service, repo):
    """A unique violation with no findable row surfaces the conflict, not None."""
    repo.raise_duplicate_on_save = True  # constraint fires...
    # ...but find_by_name turns up nothing (e.g. the other writer rolled back).

    with pytest.raises(DuplicateTagNameError):
        await service.create_tag(name="Ghost", transaction=None, user_id=OWNER)


@pytest.mark.asyncio
async def test_update_tag_basic(service, repo, publisher):
    tag = Tag(id=1, name=TagName("Test"), color="#FFFFFF", user_id=OWNER)
    await repo.save(tag, user_id=OWNER)

    updated = await service.update_tag(
        tag_id=1, transaction=None, name="Updated_Test", color="#000000", user_id=OWNER
    )

    assert str(updated.name) == "Updated_Test"
    assert str(updated.color) == "#000000"

    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert isinstance(event, TagUpdated)
    assert event.aggregate_id == 1
    assert "name" in event.event_data["changed_fields"]
    assert "color" in event.event_data["changed_fields"]
    assert event.event_data["user_id"] == OWNER


@pytest.mark.asyncio
async def test_update_tag_not_found(service):
    with pytest.raises(TagNotFoundError):
        await service.update_tag(tag_id=99, transaction=None, name="New", user_id=OWNER)


@pytest.mark.asyncio
async def test_update_tag_uniqueness_validation(service, repo, hierarchy_service):
    tag = Tag(id=1, name=TagName("Test"), user_id=OWNER)
    await repo.save(tag, user_id=OWNER)

    hierarchy_service.throw_uniqueness = True
    with pytest.raises(DuplicateTagNameError):
        await service.update_tag(
            tag_id=1, transaction=None, name="Duplicate", user_id=OWNER
        )


@pytest.mark.asyncio
async def test_update_tag_reparenting_cycle(service, repo, hierarchy_service):
    tag = Tag(id=1, name=TagName("Test"), parent_id=None, user_id=OWNER)
    await repo.save(tag, user_id=OWNER)
    parent_tag = Tag(id=2, name=TagName("Parent"), user_id=OWNER)
    await repo.save(parent_tag, user_id=OWNER)

    hierarchy_service.throw_cycle = True
    with pytest.raises(ContactValidationError):
        await service.update_tag(tag_id=1, transaction=None, parent_id=2, user_id=OWNER)


@pytest.mark.asyncio
async def test_update_tag_clear_parent(service, repo, publisher):
    tag = Tag(id=1, name=TagName("Test"), parent_id=5, user_id=OWNER)
    await repo.save(tag, user_id=OWNER)

    updated = await service.update_tag(
        tag_id=1, transaction=None, set_parent_null=True, user_id=OWNER
    )
    assert updated.parent_id is None

    event = publisher.events[0]
    assert "parent_id" in event.event_data["changed_fields"]
    assert event.event_data["changed_fields"]["parent_id"] == (5, None)


@pytest.mark.asyncio
async def test_update_tag_explicit_parent_wins_over_clear(service, repo):
    """An explicit parent takes precedence over set_parent_null."""
    tag = Tag(id=1, name=TagName("Test"), parent_id=None, user_id=OWNER)
    await repo.save(tag, user_id=OWNER)
    parent_tag = Tag(id=2, name=TagName("Parent"), user_id=OWNER)
    await repo.save(parent_tag, user_id=OWNER)

    updated = await service.update_tag(
        tag_id=1, transaction=None, parent_id=2, set_parent_null=True, user_id=OWNER
    )

    assert updated.parent_id == 2


@pytest.mark.asyncio
async def test_update_tag_unchanged_parent_is_not_cleared(service, repo):
    """A parent_id equal to the current parent must not fall through to clearing.

    The no-change case is nested inside the parent_id branch; a flat
    ``elif set_parent_null`` would clear the parent here instead of keeping it.
    """
    parent_tag = Tag(id=2, name=TagName("Parent"), user_id=OWNER)
    await repo.save(parent_tag, user_id=OWNER)
    tag = Tag(id=1, name=TagName("Test"), parent_id=2, user_id=OWNER)
    await repo.save(tag, user_id=OWNER)

    updated = await service.update_tag(
        tag_id=1, transaction=None, parent_id=2, set_parent_null=True, user_id=OWNER
    )

    assert updated.parent_id == 2


@pytest.mark.asyncio
async def test_delete_tag(service, repo, publisher):
    tag = Tag(id=1, name=TagName("To_Delete"), user_id=OWNER)
    await repo.save(tag, user_id=OWNER)

    # A real connection stand-in: deleting a tag now also marks the contacts
    # that lose it, which is SQL this service issues itself.
    await service.delete_tag(tag_id=1, transaction=AsyncMock(), user_id=OWNER)

    assert 1 in repo.deleted_ids
    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert isinstance(event, TagDeleted)
    assert event.aggregate_id == 1
    assert event.event_data["tag_name"] == "To_Delete"
    assert event.event_data["user_id"] == OWNER


@pytest.mark.asyncio
async def test_delete_tag_not_found(service):
    with pytest.raises(TagNotFoundError):
        await service.delete_tag(tag_id=99, transaction=None, user_id=OWNER)


@pytest.mark.asyncio
async def test_another_users_tag_is_not_found(service, repo):
    await repo.save(
        Tag(id=1, name=TagName("Theirs"), user_id="someone-else"),
        user_id="someone-else",
    )

    with pytest.raises(TagNotFoundError):
        await service.update_tag(tag_id=1, transaction=None, name="Mine", user_id=OWNER)
    with pytest.raises(TagNotFoundError):
        await service.delete_tag(tag_id=1, transaction=AsyncMock(), user_id=OWNER)
    assert repo.tags[1].name == TagName("Theirs")


@pytest.mark.asyncio
async def test_a_tag_cannot_sit_under_another_users_tag(service, repo):
    await repo.save(
        Tag(id=1, name=TagName("Theirs"), user_id="someone-else"),
        user_id="someone-else",
    )
    await repo.save(Tag(id=2, name=TagName("Mine"), user_id=OWNER), user_id=OWNER)

    with pytest.raises(TagNotFoundError):
        await service.create_tag(
            name="Child", transaction=None, parent_id=1, user_id=OWNER
        )
    with pytest.raises(TagNotFoundError):
        await service.update_tag(tag_id=2, transaction=None, parent_id=1, user_id=OWNER)
    assert repo.tags[2].parent_id is None
