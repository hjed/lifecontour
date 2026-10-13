"""Integration tests for TagRepository with real database."""

import pytest
from core_shared.models.contacts.entities import Contact, Tag
from core_shared.models.contacts.value_objects import TagName
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import SqlContactRepository, SqlTagRepository
from app.core.contacts.models.exceptions import DuplicateTagNameError, TagNotFoundError
from tests.integration.contact_seeding import OTHER_USER_ID, TEST_USER_ID


@pytest.mark.integration
class TestTagRepositoryIntegration:
    """Integration tests for TagRepository with real database."""

    @pytest.fixture
    def tag_repo(self, clean_database: AsyncConnection):
        """Create TagRepository instance with real database connection."""
        return SqlTagRepository(clean_database)

    @pytest.mark.asyncio
    async def test_save_new_tag(self, tag_repo):
        """Test saving a new tag to database."""
        # Arrange
        tag = Tag(
            name=TagName("work"), color="#FF0000", description="Work-related contacts"
        )

        # Act
        saved_tag = await tag_repo.save(tag, user_id=TEST_USER_ID)

        # Assert
        assert saved_tag.id is not None
        assert str(saved_tag.name) == "work"
        assert saved_tag.color == "#FF0000"
        assert saved_tag.description == "Work-related contacts"
        assert saved_tag.created_at is not None
        assert saved_tag.updated_at is not None

    @pytest.mark.asyncio
    async def test_save_update_existing_tag(self, tag_repo):
        """Test updating an existing tag in database."""
        # Arrange - Create tag
        tag = Tag(name=TagName("work"), color="#FF0000")
        saved_tag = await tag_repo.save(tag, user_id=TEST_USER_ID)

        # Update tag
        saved_tag.color = "#00FF00"
        saved_tag.description = "Updated description"

        # Act
        updated_tag = await tag_repo.save(saved_tag, user_id=TEST_USER_ID)

        # Assert
        assert updated_tag.id == saved_tag.id
        assert str(updated_tag.name) == "work"
        assert updated_tag.color == "#00FF00"
        assert updated_tag.description == "Updated description"
        assert updated_tag.updated_at is not None

        # Verify the tag was actually updated in the database
        found_tag = await tag_repo.find_by_id(saved_tag.id, user_id=TEST_USER_ID)
        assert found_tag.color == "#00FF00"
        assert found_tag.description == "Updated description"

    @pytest.mark.asyncio
    async def test_save_duplicate_name_raises_error(self, tag_repo):
        """Test saving tag with duplicate name raises error."""
        # Arrange - Create first tag
        tag1 = Tag(name=TagName("work"))
        await tag_repo.save(tag1, user_id=TEST_USER_ID)

        # Try to create second tag with same name
        tag2 = Tag(name=TagName("work"))

        # Act & Assert
        with pytest.raises(DuplicateTagNameError):
            await tag_repo.save(tag2, user_id=TEST_USER_ID)

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, tag_repo):
        """Test finding tag by ID when it exists."""
        # Arrange
        tag = Tag(name=TagName("personal"), color="#0000FF")
        saved_tag = await tag_repo.save(tag, user_id=TEST_USER_ID)

        # Act
        found_tag = await tag_repo.find_by_id(saved_tag.id, user_id=TEST_USER_ID)

        # Assert
        assert found_tag is not None
        assert found_tag.id == saved_tag.id
        assert str(found_tag.name) == "personal"
        assert found_tag.color == "#0000FF"

    @pytest.mark.asyncio
    async def test_find_by_id_not_existing(self, tag_repo):
        """Test finding tag by ID when it doesn't exist."""
        # Act
        found_tag = await tag_repo.find_by_id(999, user_id=TEST_USER_ID)

        # Assert
        assert found_tag is None

    @pytest.mark.asyncio
    async def test_find_by_name_existing(self, tag_repo):
        """Test finding tag by name when it exists."""
        # Arrange
        tag = Tag(name=TagName("client"), color="#FFFF00")
        saved_tag = await tag_repo.save(tag, user_id=TEST_USER_ID)

        # Act
        found_tag = await tag_repo.find_by_name("client", user_id=TEST_USER_ID)

        # Assert
        assert found_tag is not None
        assert found_tag.id == saved_tag.id
        assert str(found_tag.name) == "client"
        assert found_tag.color == "#FFFF00"

    @pytest.mark.asyncio
    async def test_find_by_name_not_existing(self, tag_repo):
        """Test finding tag by name when it doesn't exist."""
        # Act
        found_tag = await tag_repo.find_by_name("nonexistent", user_id=TEST_USER_ID)

        # Assert
        assert found_tag is None

    @pytest.mark.asyncio
    async def test_find_by_names(self, tag_repo):
        """Test finding multiple tags by name."""
        # Arrange
        tag1 = Tag(name=TagName("tag_a"))
        tag2 = Tag(name=TagName("tag_b"))
        tag3 = Tag(name=TagName("tag_c"))
        await tag_repo.save(tag1, user_id=TEST_USER_ID)
        await tag_repo.save(tag2, user_id=TEST_USER_ID)
        await tag_repo.save(tag3, user_id=TEST_USER_ID)

        # Act
        results = await tag_repo.find_by_names(
            ["tag_a", "tag_c", "nonexistent"], user_id=TEST_USER_ID
        )

        # Assert
        assert len(results) == 2
        assert "tag_a" in results
        assert "tag_c" in results
        assert "nonexistent" not in results
        assert str(results["tag_a"].name) == "tag_a"
        assert str(results["tag_c"].name) == "tag_c"

    @pytest.mark.asyncio
    async def test_find_by_names_case_insensitive(self, tag_repo):
        """Test finding tags by name is case insensitive and returns original casing keys."""
        # Arrange
        tag1 = Tag(name=TagName("TestTagCase"))
        await tag_repo.save(tag1, user_id=TEST_USER_ID)

        # Act
        results = await tag_repo.find_by_names(
            ["testtagcase", "TESTTAGCASE"], user_id=TEST_USER_ID
        )

        # Assert
        assert len(results) == 2
        assert "testtagcase" in results
        assert "TESTTAGCASE" in results
        assert str(results["testtagcase"].name) == "TestTagCase"
        assert str(results["TESTTAGCASE"].name) == "TestTagCase"

    @pytest.mark.asyncio
    async def test_find_by_names_empty_list(self, tag_repo):
        """Test finding tags with an empty list of names."""
        # Act
        results = await tag_repo.find_by_names([], user_id=TEST_USER_ID)

        # Assert
        assert isinstance(results, dict)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_get_all_tags(self, tag_repo):
        """Test getting all tags."""
        # Arrange - Create multiple tags
        tag1 = Tag(name=TagName("work"))
        tag2 = Tag(name=TagName("personal"))
        tag3 = Tag(name=TagName("client"))

        await tag_repo.save(tag1, user_id=TEST_USER_ID)
        await tag_repo.save(tag2, user_id=TEST_USER_ID)
        await tag_repo.save(tag3, user_id=TEST_USER_ID)

        # Act
        all_tags = await tag_repo.get_all(user_id=TEST_USER_ID)

        # Assert
        assert len(all_tags) >= 3
        tag_names = [str(tag.name) for tag in all_tags]
        assert "work" in tag_names
        assert "personal" in tag_names
        assert "client" in tag_names

    @pytest.mark.asyncio
    async def test_delete_tag(self, tag_repo):
        """Test deleting a tag."""
        # Arrange
        tag = Tag(name=TagName("temporary"))
        saved_tag = await tag_repo.save(tag, user_id=TEST_USER_ID)

        # Act
        assert await tag_repo.delete(saved_tag.id, user_id=TEST_USER_ID)

        # Assert - Tag should no longer exist
        found_tag = await tag_repo.find_by_id(saved_tag.id, user_id=TEST_USER_ID)
        assert found_tag is None

    @pytest.mark.asyncio
    async def test_deleting_a_missing_tag_reports_nothing_deleted(self, tag_repo):
        assert not await tag_repo.delete(999, user_id=TEST_USER_ID)

    @pytest.mark.asyncio
    async def test_hierarchical_tags(self, tag_repo):
        """Test creating hierarchical tags with parent-child relationships."""
        # Arrange - Create parent tag
        parent_tag = Tag(name=TagName("business"))
        saved_parent = await tag_repo.save(parent_tag, user_id=TEST_USER_ID)

        # Create child tag
        child_tag = Tag(name=TagName("client"), parent_id=saved_parent.id)

        # Act
        saved_child = await tag_repo.save(child_tag, user_id=TEST_USER_ID)

        # Assert
        assert saved_child.id is not None
        assert saved_child.parent_id == saved_parent.id
        assert str(saved_child.name) == "client"

        # Verify parent can be found
        found_parent = await tag_repo.find_by_id(saved_parent.id, user_id=TEST_USER_ID)
        assert found_parent is not None
        assert str(found_parent.name) == "business"

    @pytest.mark.asyncio
    async def test_search_tags(self, tag_repo):
        """Test searching tags by name pattern."""
        # Arrange - Create tags with similar names
        tag1 = Tag(name=TagName("work-project"))
        tag2 = Tag(name=TagName("work-meeting"))
        tag3 = Tag(name=TagName("personal"))

        await tag_repo.save(tag1, user_id=TEST_USER_ID)
        await tag_repo.save(tag2, user_id=TEST_USER_ID)
        await tag_repo.save(tag3, user_id=TEST_USER_ID)

        # Act
        results = await tag_repo.search("work", user_id=TEST_USER_ID)

        # Assert
        assert len(results) >= 2
        tag_names = [str(tag.name) for tag in results]
        assert any("work" in name for name in tag_names)

    @pytest.mark.asyncio
    async def test_get_tags_by_parent(self, tag_repo):
        """Test getting tags by parent ID."""
        # Arrange - Create parent and child tags
        parent_tag = Tag(name=TagName("categories"))
        saved_parent = await tag_repo.save(parent_tag, user_id=TEST_USER_ID)

        child1 = Tag(name=TagName("work"), parent_id=saved_parent.id)
        child2 = Tag(name=TagName("personal"), parent_id=saved_parent.id)
        orphan = Tag(name=TagName("orphan"))  # No parent

        await tag_repo.save(child1, user_id=TEST_USER_ID)
        await tag_repo.save(child2, user_id=TEST_USER_ID)
        await tag_repo.save(orphan, user_id=TEST_USER_ID)

        # Act
        children = await tag_repo.get_children(saved_parent.id, user_id=TEST_USER_ID)

        # Assert
        assert len(children) == 2
        child_names = [str(tag.name) for tag in children]
        assert "work" in child_names
        assert "personal" in child_names
        assert "orphan" not in child_names

    @pytest.mark.asyncio
    async def test_get_root_tags(self, tag_repo):
        """Test getting root tags (tags without parents)."""
        # Arrange - Create mix of root and child tags
        root1 = Tag(name=TagName("root1"))
        root2 = Tag(name=TagName("root2"))
        saved_root1 = await tag_repo.save(root1, user_id=TEST_USER_ID)
        await tag_repo.save(
            root2, user_id=TEST_USER_ID
        )  # Save but don't need to store reference

        child = Tag(name=TagName("child"), parent_id=saved_root1.id)
        await tag_repo.save(child, user_id=TEST_USER_ID)

        # Act
        root_tags = await tag_repo.get_root_tags(user_id=TEST_USER_ID)

        # Assert
        assert len(root_tags) >= 2
        root_names = [str(tag.name) for tag in root_tags]
        assert "root1" in root_names
        assert "root2" in root_names
        assert "child" not in root_names


@pytest.mark.integration
class TestTagOwnerIsRecorded:
    """Every tag is written with an owner, and every read hands it back."""

    @pytest.fixture
    def tag_repo(self, clean_database: AsyncConnection) -> SqlTagRepository:
        return SqlTagRepository(clean_database)

    async def test_save_stamps_the_owner_and_every_read_returns_it(
        self, tag_repo: SqlTagRepository
    ) -> None:
        parent = await tag_repo.save(Tag(name=TagName("crew")), user_id=TEST_USER_ID)
        assert parent.id is not None
        child = await tag_repo.save(
            Tag(name=TagName("crew/deck"), parent_id=parent.id), user_id=TEST_USER_ID
        )
        assert child.id is not None
        assert parent.user_id == TEST_USER_ID

        found = await tag_repo.find_by_id(parent.id, user_id=TEST_USER_ID)
        by_name = await tag_repo.find_by_name("crew", user_id=TEST_USER_ID)
        reads = [
            found,
            by_name,
            *(await tag_repo.find_by_names(["crew"], user_id=TEST_USER_ID)).values(),
            *await tag_repo.get_all(user_id=TEST_USER_ID),
            *await tag_repo.get_children(parent.id, user_id=TEST_USER_ID),
            *await tag_repo.get_descendants_for_tags([parent.id], user_id=TEST_USER_ID),
            *await tag_repo.get_root_tags(user_id=TEST_USER_ID),
            *await tag_repo.search("crew", user_id=TEST_USER_ID),
        ]

        assert len(reads) == 10  # get_all and search both find parent and child
        assert {tag.user_id for tag in reads if tag is not None} == {TEST_USER_ID}

    async def test_a_contacts_tags_carry_their_owner(
        self, tag_repo: SqlTagRepository, clean_database: AsyncConnection
    ) -> None:
        tag = await tag_repo.save(Tag(name=TagName("crew")), user_id=TEST_USER_ID)
        assert tag.id is not None
        contacts = SqlContactRepository(clean_database)
        contact = await contacts.save(Contact(user_id=TEST_USER_ID, first_name="Ann"))
        assert contact.id is not None
        await contacts.assign_tag(contact.id, tag.id)

        single = await contacts.find_by_id(contact.id, user_id=TEST_USER_ID)
        batch = await contacts.get_all(user_id=TEST_USER_ID)

        assert single is not None and single.tags is not None
        assert [t.user_id for t in single.tags] == [TEST_USER_ID]
        assert [t.user_id for c in batch for t in c.tags or []] == [TEST_USER_ID]


@pytest.mark.integration
class TestTagReadsAreScopedToTheOwner:
    """Another user's tag, even one of the same name, is invisible to every read."""

    @pytest.fixture
    def tag_repo(self, clean_database: AsyncConnection) -> SqlTagRepository:
        return SqlTagRepository(clean_database)

    @pytest.fixture
    async def tags(self, tag_repo: SqlTagRepository) -> dict[str, Tag]:
        """The same tree for both owners: ``crew`` > ``crew/deck``."""
        tags: dict[str, Tag] = {}
        for owner, label in ((TEST_USER_ID, "own"), (OTHER_USER_ID, "foreign")):
            parent = await tag_repo.save(Tag(name=TagName("crew")), user_id=owner)
            assert parent.id is not None
            child = await tag_repo.save(
                Tag(name=TagName("crew/deck"), parent_id=parent.id), user_id=owner
            )
            tags[label] = parent
            tags[f"{label}_child"] = child
        return tags

    async def test_a_foreign_tag_is_not_found_by_id(
        self, tag_repo: SqlTagRepository, tags: dict[str, Tag]
    ) -> None:
        foreign_id = tags["foreign"].id
        assert foreign_id is not None

        assert await tag_repo.find_by_id(foreign_id, user_id=TEST_USER_ID) is None
        found = await tag_repo.find_by_id(foreign_id, user_id=OTHER_USER_ID)
        assert found is not None and found.user_id == OTHER_USER_ID

    async def test_a_name_resolves_to_the_users_own_tag(
        self, tag_repo: SqlTagRepository, tags: dict[str, Tag]
    ) -> None:
        by_name = await tag_repo.find_by_name("CREW", user_id=TEST_USER_ID)
        by_names = await tag_repo.find_by_names(["crew"], user_id=TEST_USER_ID)

        assert by_name is not None and by_name.id == tags["own"].id
        assert {name: tag.id for name, tag in by_names.items()} == {
            "crew": tags["own"].id
        }

    async def test_listing_reads_return_only_the_users_tags(
        self, tag_repo: SqlTagRepository, tags: dict[str, Tag]
    ) -> None:
        own_ids = {tags["own"].id, tags["own_child"].id}

        assert {t.id for t in await tag_repo.get_all(user_id=TEST_USER_ID)} == own_ids
        assert {t.id for t in await tag_repo.search("crew", user_id=TEST_USER_ID)} == (
            own_ids
        )
        assert [t.id for t in await tag_repo.get_root_tags(user_id=TEST_USER_ID)] == [
            tags["own"].id
        ]

    async def test_the_hierarchy_never_reaches_a_foreign_tag(
        self, tag_repo: SqlTagRepository, tags: dict[str, Tag]
    ) -> None:
        foreign_id = tags["foreign"].id
        assert foreign_id is not None

        assert await tag_repo.get_children(foreign_id, user_id=TEST_USER_ID) == []
        assert (
            await tag_repo.get_descendants_for_tags([foreign_id], user_id=TEST_USER_ID)
            == []
        )

    async def test_the_descendant_walk_stops_at_a_foreign_grandchild(
        self,
        tag_repo: SqlTagRepository,
        tags: dict[str, Tag],
        clean_database: AsyncConnection,
    ) -> None:
        """Every level of the walk is filtered, not only its starting point."""
        own_child = tags["own_child"]
        assert own_child.id is not None
        # A cross-owner link no write can make, seeded to prove the filter.
        await tag_repo.save(
            Tag(name=TagName("crew/deck/stray"), parent_id=own_child.id),
            user_id=OTHER_USER_ID,
        )
        own_id = tags["own"].id
        assert own_id is not None

        descendants = await tag_repo.get_descendants_for_tags(
            [own_id], user_id=TEST_USER_ID
        )

        assert [t.id for t in descendants] == [own_child.id]

    async def test_two_users_may_each_hold_the_same_name(
        self, tag_repo: SqlTagRepository, tags: dict[str, Tag]
    ) -> None:
        """Names are unique per owner, and still case-insensitively so."""
        assert tags["own"].id != tags["foreign"].id

        with pytest.raises(DuplicateTagNameError):
            await tag_repo.save(Tag(name=TagName("Crew")), user_id=TEST_USER_ID)


@pytest.mark.integration
class TestTagWritesAreScopedToTheOwner:
    """A write naming another user's tag changes nothing of theirs."""

    @pytest.fixture
    def tag_repo(self, clean_database: AsyncConnection) -> SqlTagRepository:
        return SqlTagRepository(clean_database)

    @pytest.fixture
    async def foreign(self, tag_repo: SqlTagRepository) -> Tag:
        return await tag_repo.save(Tag(name=TagName("theirs")), user_id=OTHER_USER_ID)

    @staticmethod
    async def _tag_rows(conn: AsyncConnection) -> list[tuple[object, ...]]:
        rows = await conn.execute(
            text("SELECT id, user_id, name, parent_id FROM tags ORDER BY id")
        )
        return [tuple(row) for row in rows]

    @staticmethod
    async def _assignments(conn: AsyncConnection) -> set[tuple[int, int]]:
        rows = await conn.execute(text("SELECT contact_id, tag_id FROM contact_tags"))
        return {(row.contact_id, row.tag_id) for row in rows}

    async def test_saving_a_foreign_tag_changes_nothing(
        self,
        tag_repo: SqlTagRepository,
        foreign: Tag,
        clean_database: AsyncConnection,
    ) -> None:
        before = await self._tag_rows(clean_database)
        foreign.name = TagName("renamed")

        with pytest.raises(TagNotFoundError):
            await tag_repo.save(foreign, user_id=TEST_USER_ID)

        assert await self._tag_rows(clean_database) == before

    async def test_deleting_a_foreign_tag_changes_nothing(
        self,
        tag_repo: SqlTagRepository,
        foreign: Tag,
        clean_database: AsyncConnection,
    ) -> None:
        assert foreign.id is not None
        before = await self._tag_rows(clean_database)

        assert not await tag_repo.delete(foreign.id, user_id=TEST_USER_ID)

        assert await self._tag_rows(clean_database) == before

    async def test_merging_with_a_foreign_tag_moves_nothing(
        self,
        tag_repo: SqlTagRepository,
        foreign: Tag,
        clean_database: AsyncConnection,
    ) -> None:
        own = await tag_repo.save(Tag(name=TagName("mine")), user_id=TEST_USER_ID)
        assert own.id is not None and foreign.id is not None
        contacts = SqlContactRepository(clean_database)
        theirs = await contacts.save(Contact(user_id=OTHER_USER_ID, first_name="Bo"))
        assert theirs.id is not None
        await contacts.assign_tag(theirs.id, foreign.id)
        before = (
            await self._tag_rows(clean_database),
            await self._assignments(clean_database),
        )

        assert not await tag_repo.merge_into(foreign.id, own.id, user_id=TEST_USER_ID)
        assert not await tag_repo.merge_into(own.id, foreign.id, user_id=TEST_USER_ID)

        after = (
            await self._tag_rows(clean_database),
            await self._assignments(clean_database),
        )
        assert after == before

    async def test_a_merge_adopts_only_the_owners_children(
        self, tag_repo: SqlTagRepository, clean_database: AsyncConnection
    ) -> None:
        source = await tag_repo.save(Tag(name=TagName("old")), user_id=TEST_USER_ID)
        target = await tag_repo.save(Tag(name=TagName("new")), user_id=TEST_USER_ID)
        assert source.id is not None and target.id is not None
        child = await tag_repo.save(
            Tag(name=TagName("old/kid"), parent_id=source.id), user_id=TEST_USER_ID
        )
        # A cross-owner link no write can make, seeded to prove the filter.
        stray = await tag_repo.save(
            Tag(name=TagName("stray"), parent_id=source.id), user_id=OTHER_USER_ID
        )

        assert await tag_repo.merge_into(source.id, target.id, user_id=TEST_USER_ID)

        rows = await clean_database.execute(text("SELECT id, parent_id FROM tags"))
        parents = {row.id: row.parent_id for row in rows}
        assert parents[child.id] == target.id
        assert parents[stray.id] == source.id

    async def test_a_contact_never_receives_another_users_tag(
        self, foreign: Tag, clean_database: AsyncConnection
    ) -> None:
        assert foreign.id is not None
        contacts = SqlContactRepository(clean_database)
        own = await contacts.save(Contact(user_id=TEST_USER_ID, first_name="Ann"))
        assert own.id is not None

        assert not await contacts.assign_tag(own.id, foreign.id)

        assert await self._assignments(clean_database) == set()

    async def test_assigning_your_own_tag_reports_it_held_even_when_it_was(
        self, tag_repo: SqlTagRepository, clean_database: AsyncConnection
    ) -> None:
        mine = await tag_repo.save(Tag(name=TagName("mine")), user_id=TEST_USER_ID)
        assert mine.id is not None
        contacts = SqlContactRepository(clean_database)
        own = await contacts.save(Contact(user_id=TEST_USER_ID, first_name="Ann"))
        assert own.id is not None

        assert await contacts.assign_tag(own.id, mine.id)
        assert await contacts.assign_tag(own.id, mine.id)
        assert await self._assignments(clean_database) == {(own.id, mine.id)}
