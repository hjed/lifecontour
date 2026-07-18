"""Unit tests for JournalTagService."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from core_shared.models.journals import (
    JournalTagNotFoundError,
    JournalValidationError,
)
from sqlalchemy.exc import IntegrityError

from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.services.journal_tag_hierarchy_service import (
    JournalTagHierarchyService,
)
from app.core.journal.services.journal_tag_service import (
    JournalTagInUseError,
    JournalTagService,
)


@pytest.fixture
def mock_tag_repo():
    """Create a mock journal tag repository."""
    return AsyncMock()


@pytest.fixture
def mock_transaction():
    """Create a mock transaction (not a real AsyncConnection)."""
    return AsyncMock()


@pytest.fixture
def hierarchy_service(mock_tag_repo):
    """Create a real hierarchy service over the mock repo.

    The hierarchy rules are part of the behaviour under test, so this is
    deliberately the real collaborator rather than a mock.
    """
    return JournalTagHierarchyService(mock_tag_repo)


@pytest.fixture
def tag_service(mock_tag_repo, hierarchy_service):
    """Create a JournalTagService instance."""
    return JournalTagService(mock_tag_repo, hierarchy_service)


class TestCreateTag:
    """Test the create_tag unit of work."""

    @pytest.mark.asyncio
    async def test_create_tag_persists_and_returns(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """create_tag saves via the repo and returns the saved entity."""
        tag = JournalTag(name="Work", color="#3B82F6")
        saved = JournalTag(id=uuid4(), name="Work", color="#3B82F6")
        mock_tag_repo.save.return_value = saved

        result = await tag_service.create_tag(tag, transaction=mock_transaction)

        assert result is saved
        mock_tag_repo.save.assert_awaited_once_with(tag)

    @pytest.mark.asyncio
    async def test_create_tag_maps_duplicate_name_to_validation_error(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A duplicate-name IntegrityError becomes a JournalValidationError."""
        tag = JournalTag(name="Work", color="#3B82F6")
        mock_tag_repo.save.side_effect = IntegrityError(
            "uq_journal_tags_name", {}, Exception("dup")
        )

        with pytest.raises(JournalValidationError):
            await tag_service.create_tag(tag, transaction=mock_transaction)

    @pytest.mark.asyncio
    async def test_create_tag_reraises_other_integrity_errors(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A non-duplicate IntegrityError is re-raised unchanged."""
        tag = JournalTag(name="Work", color="#3B82F6")
        mock_tag_repo.save.side_effect = IntegrityError(
            "some other constraint", {}, Exception("boom")
        )

        with pytest.raises(IntegrityError):
            await tag_service.create_tag(tag, transaction=mock_transaction)


class TestDeleteTag:
    """Test the delete_tag unit of work."""

    @staticmethod
    def _transaction_with_usage(usage_count: int) -> AsyncMock:
        """Build a mock transaction whose usage query returns ``usage_count``."""
        transaction = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = (usage_count,)
        transaction.execute.return_value = result
        return transaction

    @pytest.mark.asyncio
    async def test_delete_tag_deletes_when_unused(self, tag_service, mock_tag_repo):
        """delete_tag removes the tag when no journals reference it."""
        tag_id = uuid4()
        transaction = self._transaction_with_usage(0)

        await tag_service.delete_tag(tag_id, transaction=transaction)

        mock_tag_repo.delete.assert_awaited_once_with(tag_id)

    @pytest.mark.asyncio
    async def test_delete_tag_rejects_in_use(self, tag_service, mock_tag_repo):
        """delete_tag raises an in-use error when journals reference it."""
        tag_id = uuid4()
        transaction = self._transaction_with_usage(3)
        mock_tag_repo.find_by_id.return_value = JournalTag(
            id=tag_id, name="Busy", color="#000000"
        )

        with pytest.raises(JournalTagInUseError) as exc_info:
            await tag_service.delete_tag(tag_id, transaction=transaction)

        assert exc_info.value.status_code == 409
        mock_tag_repo.delete.assert_not_awaited()


class TestUpdateTag:
    """Test the update_tag unit of work.

    Mirrors the contact ``TagService.update_tag`` contract: case-insensitive
    name uniqueness, hex colour validation, parent-cycle prevention and
    explicit set-parent-null semantics.
    """

    @staticmethod
    def _wire_repo(mock_tag_repo, tags: list[JournalTag]) -> None:
        """Make the mock repo resolve ``find_by_id``/``find_by_name`` over ``tags``."""
        by_id = {tag.id: tag for tag in tags}
        by_name = {tag.name.lower(): tag for tag in tags}

        async def find_by_id(tag_id):
            return by_id.get(tag_id)

        async def find_by_name(name):
            return by_name.get(name.lower())

        mock_tag_repo.find_by_id.side_effect = find_by_id
        mock_tag_repo.find_by_name.side_effect = find_by_name
        mock_tag_repo.save.side_effect = lambda tag: tag

    @pytest.mark.asyncio
    async def test_update_tag_name_and_color(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """Updating name and colour persists both via the repo."""
        tag_id = uuid4()
        self._wire_repo(mock_tag_repo, [JournalTag(id=tag_id, name="Work")])

        result = await tag_service.update_tag(
            tag_id, transaction=mock_transaction, name="Career", color="#3B82F6"
        )

        assert result.name == "Career"
        assert result.color == "#3B82F6"
        saved = mock_tag_repo.save.call_args.args[0]
        assert saved.id == tag_id

    @pytest.mark.asyncio
    async def test_update_tag_description(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """Description is updatable independently of the other fields."""
        tag_id = uuid4()
        self._wire_repo(mock_tag_repo, [JournalTag(id=tag_id, name="Work")])

        result = await tag_service.update_tag(
            tag_id, transaction=mock_transaction, description="Paid work entries"
        )

        assert result.description == "Paid work entries"
        assert result.name == "Work"

    @pytest.mark.asyncio
    async def test_update_tag_duplicate_name_rejected(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A name already held by another tag is rejected, case-insensitively."""
        tag_id = uuid4()
        self._wire_repo(
            mock_tag_repo,
            [
                JournalTag(id=tag_id, name="Work"),
                JournalTag(id=uuid4(), name="Personal"),
            ],
        )

        with pytest.raises(JournalValidationError) as exc_info:
            await tag_service.update_tag(
                tag_id, transaction=mock_transaction, name="personal"
            )

        assert exc_info.value.field == "name"
        mock_tag_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_tag_same_name_different_case_on_self_allowed(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """Re-casing a tag's own name is not a uniqueness conflict."""
        tag_id = uuid4()
        self._wire_repo(mock_tag_repo, [JournalTag(id=tag_id, name="Work")])

        result = await tag_service.update_tag(
            tag_id, transaction=mock_transaction, name="WORK"
        )

        assert result.name == "WORK"

    @pytest.mark.asyncio
    async def test_update_tag_invalid_colour_rejected(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A colour that is not a 7-character hex code is rejected."""
        tag_id = uuid4()
        self._wire_repo(mock_tag_repo, [JournalTag(id=tag_id, name="Work")])

        with pytest.raises(JournalValidationError) as exc_info:
            await tag_service.update_tag(
                tag_id, transaction=mock_transaction, color="red"
            )

        assert exc_info.value.field == "color"
        mock_tag_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_tag_reparent_to_unrelated_tag(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A tag can be re-parented under an unrelated tag."""
        child_id, new_parent_id = uuid4(), uuid4()
        self._wire_repo(
            mock_tag_repo,
            [
                JournalTag(id=child_id, name="Work"),
                JournalTag(id=new_parent_id, name="Life"),
            ],
        )

        result = await tag_service.update_tag(
            child_id, transaction=mock_transaction, parent_id=new_parent_id
        )

        assert result.parent_id == new_parent_id

    @pytest.mark.asyncio
    async def test_update_tag_self_parent_rejected(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A tag cannot be its own parent."""
        tag_id = uuid4()
        self._wire_repo(mock_tag_repo, [JournalTag(id=tag_id, name="Work")])

        with pytest.raises(JournalValidationError) as exc_info:
            await tag_service.update_tag(
                tag_id, transaction=mock_transaction, parent_id=tag_id
            )

        assert exc_info.value.field == "parent_id"
        mock_tag_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_tag_cycle_rejected(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A tag cannot become its own ancestor (parent -> child -> parent)."""
        parent_id, child_id = uuid4(), uuid4()
        self._wire_repo(
            mock_tag_repo,
            [
                JournalTag(id=parent_id, name="Work"),
                JournalTag(id=child_id, name="Meetings", parent_id=parent_id),
            ],
        )

        # Making the parent a child of its own descendant would close a loop.
        with pytest.raises(JournalValidationError) as exc_info:
            await tag_service.update_tag(
                parent_id, transaction=mock_transaction, parent_id=child_id
            )

        assert exc_info.value.field == "parent_id"
        mock_tag_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_tag_unknown_parent_rejected(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """Re-parenting under a tag that does not exist is rejected."""
        tag_id = uuid4()
        self._wire_repo(mock_tag_repo, [JournalTag(id=tag_id, name="Work")])

        with pytest.raises(JournalTagNotFoundError):
            await tag_service.update_tag(
                tag_id, transaction=mock_transaction, parent_id=uuid4()
            )

    @pytest.mark.asyncio
    async def test_update_tag_clear_parent(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """set_parent_null moves the tag back to the root."""
        parent_id, child_id = uuid4(), uuid4()
        self._wire_repo(
            mock_tag_repo,
            [
                JournalTag(id=parent_id, name="Work"),
                JournalTag(id=child_id, name="Meetings", parent_id=parent_id),
            ],
        )

        result = await tag_service.update_tag(
            child_id, transaction=mock_transaction, set_parent_null=True
        )

        assert result.parent_id is None

    @pytest.mark.asyncio
    async def test_update_tag_omitted_parent_left_unchanged(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """Omitting parent_id leaves the existing parent in place."""
        parent_id, child_id = uuid4(), uuid4()
        self._wire_repo(
            mock_tag_repo,
            [
                JournalTag(id=parent_id, name="Work"),
                JournalTag(id=child_id, name="Meetings", parent_id=parent_id),
            ],
        )

        result = await tag_service.update_tag(
            child_id, transaction=mock_transaction, name="Standups"
        )

        assert result.parent_id == parent_id

    @pytest.mark.asyncio
    async def test_update_tag_explicit_parent_wins_over_clear(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """An explicit parent takes precedence over set_parent_null.

        Matches the contact TagService precedence, so the two MCP tools behave
        identically when a caller supplies both arguments.
        """
        child_id, new_parent_id = uuid4(), uuid4()
        self._wire_repo(
            mock_tag_repo,
            [
                JournalTag(id=child_id, name="Work"),
                JournalTag(id=new_parent_id, name="Life"),
            ],
        )

        result = await tag_service.update_tag(
            child_id,
            transaction=mock_transaction,
            parent_id=new_parent_id,
            set_parent_null=True,
        )

        assert result.parent_id == new_parent_id

    @pytest.mark.asyncio
    async def test_update_tag_maps_duplicate_name_race_to_validation_error(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A name taken between the check and the write maps to a domain error.

        The uniqueness pre-check cannot rule out a concurrent insert, so the
        save must map the constraint violation the same way create_tag does.
        """
        tag_id = uuid4()
        self._wire_repo(mock_tag_repo, [JournalTag(id=tag_id, name="Work")])
        mock_tag_repo.save.side_effect = IntegrityError(
            "uq_journal_tags_name", {}, Exception("dup")
        )

        with pytest.raises(JournalValidationError) as exc_info:
            await tag_service.update_tag(
                tag_id, transaction=mock_transaction, name="Career"
            )

        assert exc_info.value.field == "name"

    @pytest.mark.asyncio
    async def test_update_tag_not_found(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """Updating a tag that does not exist raises a 404 domain error."""
        self._wire_repo(mock_tag_repo, [])

        with pytest.raises(JournalTagNotFoundError) as exc_info:
            await tag_service.update_tag(
                uuid4(), transaction=mock_transaction, name="Nope"
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_tag_no_changes_is_noop(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """Calling update with nothing to change does not touch the repo."""
        tag_id = uuid4()
        existing = JournalTag(id=tag_id, name="Work", color="#3B82F6")
        self._wire_repo(mock_tag_repo, [existing])

        result = await tag_service.update_tag(tag_id, transaction=mock_transaction)

        assert result == existing
        mock_tag_repo.save.assert_not_awaited()


class TestAssignAndRemoveTag:
    """Test the journal<->tag assignment units of work."""

    @pytest.mark.asyncio
    async def test_assign_tag(self, tag_service, mock_tag_repo, mock_transaction):
        """assign_tag delegates to the repo."""
        tag_id = uuid4()
        await tag_service.assign_tag(7, tag_id, transaction=mock_transaction)
        mock_tag_repo.assign_tag.assert_awaited_once_with(7, tag_id)

    @pytest.mark.asyncio
    async def test_remove_tag(self, tag_service, mock_tag_repo, mock_transaction):
        """remove_tag delegates to the repo."""
        tag_id = uuid4()
        await tag_service.remove_tag(7, tag_id, transaction=mock_transaction)
        mock_tag_repo.remove_tag.assert_awaited_once_with(7, tag_id)
