"""Unit tests for JournalTagService."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from core_shared.models.history import Provenance
from core_shared.models.journals import (
    JournalTagNotFoundError,
    JournalValidationError,
)
from sqlalchemy.exc import IntegrityError

from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.services.journal_tag_hierarchy_service import (
    JournalTagHierarchyService,
)
from app.core.journal.services.journal_tag_service import JournalTagService
from tests.integration.contact_seeding import OTHER_USER_ID, TEST_USER_ID


@pytest.fixture
def mock_tag_repo():
    """Create a mock journal tag repository."""
    repo = AsyncMock()
    # Renames fan out over this list, so it must be iterable by default. Left
    # empty so a test that cares about the fan-out has to say so explicitly.
    repo.get_journal_ids_for_tag.return_value = []
    # Destructive writes report whether they changed anything.
    repo.delete.return_value = True
    repo.merge_into.return_value = True
    return repo


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
def mock_event_publisher():
    """Create a mock outbox event publisher."""
    return AsyncMock()


@pytest.fixture
def tag_service(mock_tag_repo, hierarchy_service, mock_event_publisher):
    """Create a JournalTagService instance."""
    return JournalTagService(mock_tag_repo, hierarchy_service, mock_event_publisher)


def _owned_by(tag: JournalTag | None, user_id: str) -> JournalTag | None:
    """What an owner-scoped repository read returns: the tag only for its owner."""
    return tag if tag is not None and tag.user_id == user_id else None


def _published(mock_event_publisher):
    """The events passed to ``publish``, in order."""
    return [call.args[0] for call in mock_event_publisher.publish.await_args_list]


class TestCreateTag:
    """Test the create_tag unit of work."""

    @pytest.mark.asyncio
    async def test_create_tag_persists_and_returns(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """create_tag saves via the repo and returns the saved entity."""
        tag = JournalTag(user_id=TEST_USER_ID, name="Work", color="#3B82F6")
        saved = JournalTag(
            user_id=TEST_USER_ID, id=uuid4(), name="Work", color="#3B82F6"
        )
        mock_tag_repo.save.return_value = saved

        result = await tag_service.create_tag(tag, transaction=mock_transaction)

        assert result is saved
        mock_tag_repo.save.assert_awaited_once_with(tag)

    @pytest.mark.asyncio
    async def test_create_tag_maps_duplicate_name_to_validation_error(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A duplicate-name IntegrityError becomes a JournalValidationError."""
        tag = JournalTag(user_id=TEST_USER_ID, name="Work", color="#3B82F6")
        mock_tag_repo.save.side_effect = IntegrityError(
            "uq_journal_tags_user_id_name_lower", {}, Exception("dup")
        )

        with pytest.raises(JournalValidationError):
            await tag_service.create_tag(tag, transaction=mock_transaction)

    @pytest.mark.asyncio
    async def test_create_tag_reraises_other_integrity_errors(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A non-duplicate IntegrityError is re-raised unchanged."""
        tag = JournalTag(user_id=TEST_USER_ID, name="Work", color="#3B82F6")
        mock_tag_repo.save.side_effect = IntegrityError(
            "some other constraint", {}, Exception("boom")
        )

        with pytest.raises(IntegrityError):
            await tag_service.create_tag(tag, transaction=mock_transaction)


class TestDeleteTag:
    """Test the delete_tag unit of work.

    Mirrors the contact ``TagService.delete_tag`` contract: deleting a tag
    always succeeds, un-assigning it from every journal rather than blocking.
    """

    @pytest.mark.asyncio
    async def test_delete_tag_deletes_when_unused(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """delete_tag removes the tag when no journals reference it."""
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Spare", color="#000000"
        )

        await tag_service.delete_tag(
            tag_id, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        mock_tag_repo.delete.assert_awaited_once_with(tag_id, user_id=TEST_USER_ID)

    @pytest.mark.asyncio
    async def test_delete_tag_removes_tag_in_use(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A tag assigned to journals is deleted, matching contact behaviour.

        The assignments are removed by the ``ON DELETE CASCADE`` FK, so the
        service issues no usage check and never blocks the delete.
        """
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Busy", color="#000000"
        )

        await tag_service.delete_tag(
            tag_id, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        mock_tag_repo.delete.assert_awaited_once_with(tag_id, user_id=TEST_USER_ID)
        mock_transaction.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_tag_raises_not_found_for_missing_tag(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """An unknown tag id raises the journal not-found error (404)."""
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = None

        with pytest.raises(JournalTagNotFoundError):
            await tag_service.delete_tag(
                tag_id, transaction=mock_transaction, user_id=TEST_USER_ID
            )

        mock_tag_repo.delete.assert_not_awaited()


class TestDeleteTagEvents:
    """Deleting a tag publishes one event per journal that carried it.

    The tag itself is not an aggregate with a feed — the journals that lose it
    are, so a tag-scoped write fans out to journal-scoped events, exactly as a
    rename does.
    """

    @pytest.mark.asyncio
    async def test_delete_publishes_one_event_per_tagged_journal(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.get_journal_ids_for_tag.return_value = [7, 9]

        await tag_service.delete_tag(
            tag_id,
            transaction=mock_transaction,
            source=Provenance.UI,
            changed_by="ui",
            user_id=TEST_USER_ID,
        )

        first, second = _published(mock_event_publisher)
        assert [e.event_type for e in (first, second)] == [
            "JournalTagDeleted",
            "JournalTagDeleted",
        ]
        assert [e.aggregate_id for e in (first, second)] == [7, 9]
        for event in (first, second):
            assert event.event_data["tag_id"] == str(tag_id)
            assert event.event_data["tag_name"] == "Hiking"
            assert event.event_data["source"] == Provenance.UI.value
            assert event.event_data["changed_by"] == "ui"
            assert event.transaction is mock_transaction

    @pytest.mark.asyncio
    async def test_delete_forwards_mcp_provenance(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        """The caller's provenance reaches the event, rather than a hardcoded one."""
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.get_journal_ids_for_tag.return_value = [7]

        await tag_service.delete_tag(
            tag_id,
            transaction=mock_transaction,
            source=Provenance.MCP,
            changed_by="mcp",
            user_id=TEST_USER_ID,
        )

        (event,) = _published(mock_event_publisher)
        assert event.event_data["source"] == Provenance.MCP.value
        assert event.event_data["changed_by"] == "mcp"

    @pytest.mark.asyncio
    async def test_delete_of_an_unassigned_tag_publishes_nothing(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        """No journal carried the tag, so no journal changed."""
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Spare"
        )
        mock_tag_repo.get_journal_ids_for_tag.return_value = []

        await tag_service.delete_tag(
            tag_id, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_affected_journals_are_read_before_the_delete(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        """The assignment rows cascade away, so the read cannot follow the delete.

        Simulated by having ``delete`` empty the list the repository would return
        afterwards: if the service asked for the journals after deleting the tag,
        it would find none and publish nothing.
        """
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.get_journal_ids_for_tag.return_value = [7, 9]

        async def _cascade(_tag_id, *, user_id):
            mock_tag_repo.get_journal_ids_for_tag.return_value = []
            return True

        mock_tag_repo.delete.side_effect = _cascade

        await tag_service.delete_tag(
            tag_id, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        assert [e.aggregate_id for e in _published(mock_event_publisher)] == [7, 9]


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

        async def find_by_id(tag_id, *, user_id):
            return _owned_by(by_id.get(tag_id), user_id)

        async def find_by_name(name, *, user_id):
            return _owned_by(by_name.get(name.lower()), user_id)

        mock_tag_repo.find_by_id.side_effect = find_by_id
        mock_tag_repo.find_by_name.side_effect = find_by_name
        mock_tag_repo.save.side_effect = lambda tag: tag

    @pytest.mark.asyncio
    async def test_update_tag_name_and_color(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """Updating name and colour persists both via the repo."""
        tag_id = uuid4()
        self._wire_repo(
            mock_tag_repo, [JournalTag(user_id=TEST_USER_ID, id=tag_id, name="Work")]
        )

        result = await tag_service.update_tag(
            tag_id,
            transaction=mock_transaction,
            name="Career",
            color="#3B82F6",
            user_id=TEST_USER_ID,
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
        self._wire_repo(
            mock_tag_repo, [JournalTag(user_id=TEST_USER_ID, id=tag_id, name="Work")]
        )

        result = await tag_service.update_tag(
            tag_id,
            transaction=mock_transaction,
            description="Paid work entries",
            user_id=TEST_USER_ID,
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
                JournalTag(user_id=TEST_USER_ID, id=tag_id, name="Work"),
                JournalTag(user_id=TEST_USER_ID, id=uuid4(), name="Personal"),
            ],
        )

        with pytest.raises(JournalValidationError) as exc_info:
            await tag_service.update_tag(
                tag_id,
                transaction=mock_transaction,
                name="personal",
                user_id=TEST_USER_ID,
            )

        assert exc_info.value.field == "name"
        mock_tag_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_tag_same_name_different_case_on_self_allowed(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """Re-casing a tag's own name is not a uniqueness conflict."""
        tag_id = uuid4()
        self._wire_repo(
            mock_tag_repo, [JournalTag(user_id=TEST_USER_ID, id=tag_id, name="Work")]
        )

        result = await tag_service.update_tag(
            tag_id, transaction=mock_transaction, name="WORK", user_id=TEST_USER_ID
        )

        assert result.name == "WORK"

    @pytest.mark.asyncio
    async def test_update_tag_invalid_colour_rejected(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A colour that is not a 7-character hex code is rejected."""
        tag_id = uuid4()
        self._wire_repo(
            mock_tag_repo, [JournalTag(user_id=TEST_USER_ID, id=tag_id, name="Work")]
        )

        with pytest.raises(JournalValidationError) as exc_info:
            await tag_service.update_tag(
                tag_id, transaction=mock_transaction, color="red", user_id=TEST_USER_ID
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
                JournalTag(user_id=TEST_USER_ID, id=child_id, name="Work"),
                JournalTag(user_id=TEST_USER_ID, id=new_parent_id, name="Life"),
            ],
        )

        result = await tag_service.update_tag(
            child_id,
            transaction=mock_transaction,
            parent_id=new_parent_id,
            user_id=TEST_USER_ID,
        )

        assert result.parent_id == new_parent_id

    @pytest.mark.asyncio
    async def test_update_tag_self_parent_rejected(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A tag cannot be its own parent."""
        tag_id = uuid4()
        self._wire_repo(
            mock_tag_repo, [JournalTag(user_id=TEST_USER_ID, id=tag_id, name="Work")]
        )

        with pytest.raises(JournalValidationError) as exc_info:
            await tag_service.update_tag(
                tag_id,
                transaction=mock_transaction,
                parent_id=tag_id,
                user_id=TEST_USER_ID,
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
                JournalTag(user_id=TEST_USER_ID, id=parent_id, name="Work"),
                JournalTag(
                    user_id=TEST_USER_ID,
                    id=child_id,
                    name="Meetings",
                    parent_id=parent_id,
                ),
            ],
        )

        # Making the parent a child of its own descendant would close a loop.
        with pytest.raises(JournalValidationError) as exc_info:
            await tag_service.update_tag(
                parent_id,
                transaction=mock_transaction,
                parent_id=child_id,
                user_id=TEST_USER_ID,
            )

        assert exc_info.value.field == "parent_id"
        mock_tag_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_tag_unknown_parent_rejected(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """Re-parenting under a tag that does not exist is rejected."""
        tag_id = uuid4()
        self._wire_repo(
            mock_tag_repo, [JournalTag(user_id=TEST_USER_ID, id=tag_id, name="Work")]
        )

        with pytest.raises(JournalTagNotFoundError):
            await tag_service.update_tag(
                tag_id,
                transaction=mock_transaction,
                parent_id=uuid4(),
                user_id=TEST_USER_ID,
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
                JournalTag(user_id=TEST_USER_ID, id=parent_id, name="Work"),
                JournalTag(
                    user_id=TEST_USER_ID,
                    id=child_id,
                    name="Meetings",
                    parent_id=parent_id,
                ),
            ],
        )

        result = await tag_service.update_tag(
            child_id,
            transaction=mock_transaction,
            set_parent_null=True,
            user_id=TEST_USER_ID,
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
                JournalTag(user_id=TEST_USER_ID, id=parent_id, name="Work"),
                JournalTag(
                    user_id=TEST_USER_ID,
                    id=child_id,
                    name="Meetings",
                    parent_id=parent_id,
                ),
            ],
        )

        result = await tag_service.update_tag(
            child_id,
            transaction=mock_transaction,
            name="Standups",
            user_id=TEST_USER_ID,
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
                JournalTag(user_id=TEST_USER_ID, id=child_id, name="Work"),
                JournalTag(user_id=TEST_USER_ID, id=new_parent_id, name="Life"),
            ],
        )

        result = await tag_service.update_tag(
            child_id,
            transaction=mock_transaction,
            parent_id=new_parent_id,
            set_parent_null=True,
            user_id=TEST_USER_ID,
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
        self._wire_repo(
            mock_tag_repo, [JournalTag(user_id=TEST_USER_ID, id=tag_id, name="Work")]
        )
        mock_tag_repo.save.side_effect = IntegrityError(
            "uq_journal_tags_user_id_name_lower", {}, Exception("dup")
        )

        with pytest.raises(JournalValidationError) as exc_info:
            await tag_service.update_tag(
                tag_id,
                transaction=mock_transaction,
                name="Career",
                user_id=TEST_USER_ID,
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
                uuid4(), transaction=mock_transaction, name="Nope", user_id=TEST_USER_ID
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_tag_no_changes_is_noop(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """Calling update with nothing to change does not touch the repo."""
        tag_id = uuid4()
        existing = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Work", color="#3B82F6"
        )
        self._wire_repo(mock_tag_repo, [existing])

        result = await tag_service.update_tag(
            tag_id, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        assert result == existing
        mock_tag_repo.save.assert_not_awaited()


class TestMergeTag:
    """Test the merge_tag unit of work.

    Mirrors the contact ``TagService.merge_tags`` contract: the source tag's
    assignments move to the target, its children are re-parented to the target,
    and the source is deleted. The row-level work lives in the repository, so
    these tests assert the validation rules and the delegation.
    """

    @staticmethod
    def _wire_repo(mock_tag_repo, tags: list[JournalTag]) -> None:
        """Make the mock repo resolve ``find_by_id`` over ``tags``."""
        by_id = {tag.id: tag for tag in tags}

        async def find_by_id(tag_id, *, user_id):
            return _owned_by(by_id.get(tag_id), user_id)

        mock_tag_repo.find_by_id.side_effect = find_by_id

    @pytest.mark.asyncio
    async def test_merge_delegates_to_repository(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A valid merge delegates the row work to the repository."""
        source_id, target_id = uuid4(), uuid4()
        self._wire_repo(
            mock_tag_repo,
            [
                JournalTag(user_id=TEST_USER_ID, id=source_id, name="Hiking"),
                JournalTag(user_id=TEST_USER_ID, id=target_id, name="Bushwalking"),
            ],
        )

        await tag_service.merge_tag(
            source_id, target_id, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        mock_tag_repo.merge_into.assert_awaited_once_with(
            source_id, target_id, user_id=TEST_USER_ID
        )

    @pytest.mark.asyncio
    async def test_merge_into_unrelated_tag_with_parent_allowed(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A target whose ancestry does not include the source is a legal target."""
        source_id, target_id, other_id = uuid4(), uuid4(), uuid4()
        self._wire_repo(
            mock_tag_repo,
            [
                JournalTag(user_id=TEST_USER_ID, id=source_id, name="Hiking"),
                JournalTag(user_id=TEST_USER_ID, id=other_id, name="Outdoors"),
                JournalTag(
                    user_id=TEST_USER_ID,
                    id=target_id,
                    name="Bushwalking",
                    parent_id=other_id,
                ),
            ],
        )

        await tag_service.merge_tag(
            source_id, target_id, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        mock_tag_repo.merge_into.assert_awaited_once_with(
            source_id, target_id, user_id=TEST_USER_ID
        )

    @pytest.mark.asyncio
    async def test_merge_into_self_rejected(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """Merging a tag into itself is rejected before any write."""
        tag_id = uuid4()
        self._wire_repo(
            mock_tag_repo, [JournalTag(user_id=TEST_USER_ID, id=tag_id, name="Hiking")]
        )

        with pytest.raises(JournalValidationError) as exc_info:
            await tag_service.merge_tag(
                tag_id, tag_id, transaction=mock_transaction, user_id=TEST_USER_ID
            )

        assert exc_info.value.field == "target_tag_id"
        mock_tag_repo.merge_into.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_merge_unknown_source_rejected(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """An unknown source tag raises the journal not-found error (404)."""
        target_id = uuid4()
        self._wire_repo(
            mock_tag_repo,
            [JournalTag(user_id=TEST_USER_ID, id=target_id, name="Bushwalking")],
        )

        with pytest.raises(JournalTagNotFoundError) as exc_info:
            await tag_service.merge_tag(
                uuid4(), target_id, transaction=mock_transaction, user_id=TEST_USER_ID
            )

        assert exc_info.value.status_code == 404
        mock_tag_repo.merge_into.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_merge_unknown_target_rejected(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """An unknown target tag raises the journal not-found error (404)."""
        source_id = uuid4()
        self._wire_repo(
            mock_tag_repo,
            [JournalTag(user_id=TEST_USER_ID, id=source_id, name="Hiking")],
        )

        with pytest.raises(JournalTagNotFoundError):
            await tag_service.merge_tag(
                source_id, uuid4(), transaction=mock_transaction, user_id=TEST_USER_ID
            )

        mock_tag_repo.merge_into.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_merge_into_descendant_rejected(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """Merging a tag into its own child would orphan the hierarchy."""
        source_id, child_id = uuid4(), uuid4()
        self._wire_repo(
            mock_tag_repo,
            [
                JournalTag(user_id=TEST_USER_ID, id=source_id, name="Outdoors"),
                JournalTag(
                    user_id=TEST_USER_ID,
                    id=child_id,
                    name="Hiking",
                    parent_id=source_id,
                ),
            ],
        )

        with pytest.raises(JournalValidationError) as exc_info:
            await tag_service.merge_tag(
                source_id, child_id, transaction=mock_transaction, user_id=TEST_USER_ID
            )

        assert exc_info.value.field == "target_tag_id"
        mock_tag_repo.merge_into.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_merge_into_deep_descendant_rejected(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """The descendant check walks the whole ancestry, not just one level."""
        source_id, mid_id, leaf_id = uuid4(), uuid4(), uuid4()
        self._wire_repo(
            mock_tag_repo,
            [
                JournalTag(user_id=TEST_USER_ID, id=source_id, name="Outdoors"),
                JournalTag(
                    user_id=TEST_USER_ID, id=mid_id, name="Walking", parent_id=source_id
                ),
                JournalTag(
                    user_id=TEST_USER_ID, id=leaf_id, name="Day walks", parent_id=mid_id
                ),
            ],
        )

        with pytest.raises(JournalValidationError):
            await tag_service.merge_tag(
                source_id, leaf_id, transaction=mock_transaction, user_id=TEST_USER_ID
            )

        mock_tag_repo.merge_into.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_merge_terminates_on_cyclic_ancestry(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A pre-existing parent cycle in the data does not hang the walk.

        The hierarchy should not contain a cycle, but the ancestry walk must be
        guarded regardless so a corrupt row cannot spin the request forever.
        The corrupt-data case must also be reported as what it is: the source
        is nowhere in the target's ancestry here, so calling it a
        descendant-merge would send the caller after the wrong problem.
        """
        source_id, a_id, b_id = uuid4(), uuid4(), uuid4()
        self._wire_repo(
            mock_tag_repo,
            [
                JournalTag(user_id=TEST_USER_ID, id=source_id, name="Hiking"),
                JournalTag(user_id=TEST_USER_ID, id=a_id, name="A", parent_id=b_id),
                JournalTag(user_id=TEST_USER_ID, id=b_id, name="B", parent_id=a_id),
            ],
        )

        with pytest.raises(JournalValidationError) as exc_info:
            await tag_service.merge_tag(
                source_id, a_id, transaction=mock_transaction, user_id=TEST_USER_ID
            )

        assert "circular reference" in exc_info.value.message.lower()
        assert "descendant" not in exc_info.value.message.lower()
        mock_tag_repo.merge_into.assert_not_awaited()


class TestMergeTagEvents:
    """Merging a tag publishes one event per journal carrying the source.

    Most journals swap the source for the target. A journal that already carried
    the target only loses the source, and ``already_had_target`` is what tells
    the projection which of the two happened without a second query.
    """

    @staticmethod
    def _wire(mock_tag_repo, source: JournalTag, target: JournalTag) -> None:
        by_id = {source.id: source, target.id: target}

        async def find_by_id(tag_id, *, user_id):
            return _owned_by(by_id.get(tag_id), user_id)

        mock_tag_repo.find_by_id.side_effect = find_by_id

    @staticmethod
    def _carriers(mock_tag_repo, *, source_id, target_id, source_on, target_on) -> None:
        """Answer ``get_journal_ids_for_tag`` per tag, as the real repo would."""

        async def carriers(tag_id):
            if tag_id == source_id:
                return list(source_on)
            if tag_id == target_id:
                return list(target_on)
            return []

        mock_tag_repo.get_journal_ids_for_tag.side_effect = carriers

    @pytest.mark.asyncio
    async def test_merge_publishes_one_event_per_source_journal(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        source_id, target_id = uuid4(), uuid4()
        self._wire(
            mock_tag_repo,
            JournalTag(user_id=TEST_USER_ID, id=source_id, name="Hiking"),
            JournalTag(user_id=TEST_USER_ID, id=target_id, name="Bushwalking"),
        )
        self._carriers(
            mock_tag_repo,
            source_id=source_id,
            target_id=target_id,
            source_on=[7, 9],
            target_on=[],
        )

        await tag_service.merge_tag(
            source_id,
            target_id,
            transaction=mock_transaction,
            source=Provenance.UI,
            changed_by="ui",
            user_id=TEST_USER_ID,
        )

        first, second = _published(mock_event_publisher)
        assert [e.event_type for e in (first, second)] == [
            "JournalTagMerged",
            "JournalTagMerged",
        ]
        assert [e.aggregate_id for e in (first, second)] == [7, 9]
        for event in (first, second):
            assert event.event_data["source_tag_id"] == str(source_id)
            assert event.event_data["target_tag_id"] == str(target_id)
            assert event.event_data["source_tag_name"] == "Hiking"
            assert event.event_data["target_tag_name"] == "Bushwalking"
            assert event.event_data["already_had_target"] is False
            assert event.event_data["source"] == Provenance.UI.value
            assert event.event_data["changed_by"] == "ui"
            assert event.transaction is mock_transaction

    @pytest.mark.asyncio
    async def test_a_journal_already_carrying_the_target_is_flagged(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        """One call must flag each journal independently.

        Journal 9 already holds the target, so the merge only takes the source
        away from it; journal 7 genuinely swaps one tag for the other.
        """
        source_id, target_id = uuid4(), uuid4()
        self._wire(
            mock_tag_repo,
            JournalTag(user_id=TEST_USER_ID, id=source_id, name="Hiking"),
            JournalTag(user_id=TEST_USER_ID, id=target_id, name="Bushwalking"),
        )
        self._carriers(
            mock_tag_repo,
            source_id=source_id,
            target_id=target_id,
            source_on=[7, 9],
            target_on=[9],
        )

        await tag_service.merge_tag(
            source_id, target_id, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        flags = {
            event.aggregate_id: event.event_data["already_had_target"]
            for event in _published(mock_event_publisher)
        }
        assert flags == {7: False, 9: True}

    @pytest.mark.asyncio
    async def test_merge_forwards_mcp_provenance(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        """The caller's provenance reaches the event, not a hardcoded one."""
        source_id, target_id = uuid4(), uuid4()
        self._wire(
            mock_tag_repo,
            JournalTag(user_id=TEST_USER_ID, id=source_id, name="Hiking"),
            JournalTag(user_id=TEST_USER_ID, id=target_id, name="Bushwalking"),
        )
        self._carriers(
            mock_tag_repo,
            source_id=source_id,
            target_id=target_id,
            source_on=[7],
            target_on=[],
        )

        await tag_service.merge_tag(
            source_id,
            target_id,
            transaction=mock_transaction,
            source=Provenance.MCP,
            changed_by="mcp",
            user_id=TEST_USER_ID,
        )

        (event,) = _published(mock_event_publisher)
        assert event.event_data["source"] == Provenance.MCP.value
        assert event.event_data["changed_by"] == "mcp"

    @pytest.mark.asyncio
    async def test_merging_an_unassigned_source_publishes_nothing(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        """No journal carried the source, so no journal changed."""
        source_id, target_id = uuid4(), uuid4()
        self._wire(
            mock_tag_repo,
            JournalTag(user_id=TEST_USER_ID, id=source_id, name="Hiking"),
            JournalTag(user_id=TEST_USER_ID, id=target_id, name="Bushwalking"),
        )
        self._carriers(
            mock_tag_repo,
            source_id=source_id,
            target_id=target_id,
            source_on=[],
            target_on=[7],
        )

        await tag_service.merge_tag(
            source_id, target_id, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_rejected_merge_publishes_nothing(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        """Merging a tag into itself is refused, so it leaves no history."""
        source_id = uuid4()
        self._wire(
            mock_tag_repo,
            JournalTag(user_id=TEST_USER_ID, id=source_id, name="Hiking"),
            JournalTag(user_id=TEST_USER_ID, id=source_id, name="Hiking"),
        )

        with pytest.raises(JournalValidationError):
            await tag_service.merge_tag(
                source_id, source_id, transaction=mock_transaction, user_id=TEST_USER_ID
            )

        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_carriers_are_read_before_the_merge(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        """``merge_into`` re-points and de-duplicates the rows the flags come from.

        Simulated by having it answer as the post-merge database would: the
        source carries nobody and the target carries everyone. Reading after the
        merge would publish nothing and flag nothing.
        """
        source_id, target_id = uuid4(), uuid4()
        self._wire(
            mock_tag_repo,
            JournalTag(user_id=TEST_USER_ID, id=source_id, name="Hiking"),
            JournalTag(user_id=TEST_USER_ID, id=target_id, name="Bushwalking"),
        )
        self._carriers(
            mock_tag_repo,
            source_id=source_id,
            target_id=target_id,
            source_on=[7, 9],
            target_on=[9],
        )

        async def _merged(_source_id, _target_id, *, user_id):
            self._carriers(
                mock_tag_repo,
                source_id=source_id,
                target_id=target_id,
                source_on=[],
                target_on=[7, 9],
            )
            return True

        mock_tag_repo.merge_into.side_effect = _merged

        await tag_service.merge_tag(
            source_id, target_id, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        flags = {
            event.aggregate_id: event.event_data["already_had_target"]
            for event in _published(mock_event_publisher)
        }
        assert flags == {7: False, 9: True}


class TestAssignAndRemoveTag:
    """Test the journal<->tag assignment units of work."""

    @pytest.mark.asyncio
    async def test_assign_tag(self, tag_service, mock_tag_repo, mock_transaction):
        """assign_tag delegates to the repo."""
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.assign_tag.return_value = True

        await tag_service.assign_tag(
            7, tag_id, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        mock_tag_repo.assign_tag.assert_awaited_once_with(
            7, tag_id, user_id=TEST_USER_ID
        )

    @pytest.mark.asyncio
    async def test_remove_tag(self, tag_service, mock_tag_repo, mock_transaction):
        """remove_tag delegates to the repo."""
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.remove_tag.return_value = True

        await tag_service.remove_tag(
            7, tag_id, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        mock_tag_repo.remove_tag.assert_awaited_once_with(7, tag_id)


class TestAssignAndRemoveTagEvents:
    """Tag assignment/removal publishes journal-scoped history events.

    The events name the tag (``tag_name``) so the history projection needs no
    join, and carry the caller's provenance so the activity feed can distinguish
    a UI edit from an AI-agent one.
    """

    @pytest.mark.asyncio
    async def test_assign_publishes_journal_tag_assigned(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.assign_tag.return_value = True

        await tag_service.assign_tag(
            7,
            tag_id,
            transaction=mock_transaction,
            source=Provenance.UI,
            changed_by="ui",
            user_id=TEST_USER_ID,
        )

        (event,) = _published(mock_event_publisher)
        assert event.event_type == "JournalTagAssigned"
        assert event.aggregate_id == 7
        assert event.event_data["tag_id"] == str(tag_id)
        assert event.event_data["tag_name"] == "Hiking"
        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"
        assert event.transaction is mock_transaction

    @pytest.mark.asyncio
    async def test_remove_publishes_journal_tag_removed(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.remove_tag.return_value = True

        await tag_service.remove_tag(
            7,
            tag_id,
            transaction=mock_transaction,
            source=Provenance.MCP,
            changed_by="mcp",
            user_id=TEST_USER_ID,
        )

        (event,) = _published(mock_event_publisher)
        assert event.event_type == "JournalTagRemoved"
        assert event.event_data["tag_name"] == "Hiking"
        assert event.event_data["source"] == Provenance.MCP.value
        assert event.event_data["changed_by"] == "mcp"

    @pytest.mark.asyncio
    async def test_events_default_to_system_provenance(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.assign_tag.return_value = True

        await tag_service.assign_tag(
            7, tag_id, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        (event,) = _published(mock_event_publisher)
        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

    @pytest.mark.asyncio
    async def test_assigning_an_already_assigned_tag_publishes_nothing(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        """The junction insert is ON CONFLICT DO NOTHING, so a repeat is a no-op.

        Publishing anyway would put an "Added Tags" entry in the feed for a change
        that never happened — the activity-history spec forbids exactly that.
        """
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.assign_tag.return_value = False

        await tag_service.assign_tag(
            7, tag_id, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_removing_an_unassigned_tag_publishes_nothing(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.remove_tag.return_value = False

        await tag_service.remove_tag(
            7, tag_id, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_assigning_a_missing_tag_raises_and_publishes_nothing(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = None

        with pytest.raises(JournalTagNotFoundError):
            await tag_service.assign_tag(
                7, tag_id, transaction=mock_transaction, user_id=TEST_USER_ID
            )

        mock_tag_repo.assign_tag.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_removing_a_missing_tag_is_a_silent_no_op(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        """Removal must not start raising for an unknown tag.

        To the caller an unknown tag and an unassigned one are the same outcome,
        and the DELETE endpoint has always answered both with a successful no-op —
        so loading the tag for its event name must not change that.
        """
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = None

        await tag_service.remove_tag(
            7, tag_id, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        mock_tag_repo.remove_tag.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()


class TestRenameTagEvents:
    """Renaming a tag publishes one event per journal that carries it.

    A journal's own feed is where the change is visible, so the tag-scoped write
    fans out to journal-scoped events. Only the *name* qualifies: colour,
    description and parent are tag-namespace attributes that are invisible on a
    journal, and the activity-history spec forbids recording a change that did
    not alter the entity.
    """

    @pytest.mark.asyncio
    async def test_rename_publishes_one_event_per_tagged_journal(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.find_by_name.return_value = None
        mock_tag_repo.get_journal_ids_for_tag.return_value = [7, 9]
        mock_tag_repo.save.side_effect = lambda tag: tag

        await tag_service.update_tag(
            tag_id,
            transaction=mock_transaction,
            name="Trekking",
            source=Provenance.UI,
            changed_by="ui",
            user_id=TEST_USER_ID,
        )

        first, second = _published(mock_event_publisher)
        assert [e.event_type for e in (first, second)] == [
            "JournalTagRenamed",
            "JournalTagRenamed",
        ]
        assert [e.aggregate_id for e in (first, second)] == [7, 9]
        for event in (first, second):
            assert event.event_data["tag_id"] == str(tag_id)
            assert event.event_data["old_name"] == "Hiking"
            assert event.event_data["new_name"] == "Trekking"
            assert event.event_data["source"] == Provenance.UI.value
            assert event.event_data["changed_by"] == "ui"
            assert event.transaction is mock_transaction

    @pytest.mark.asyncio
    async def test_rename_defaults_to_system_provenance(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.find_by_name.return_value = None
        mock_tag_repo.get_journal_ids_for_tag.return_value = [7]
        mock_tag_repo.save.side_effect = lambda tag: tag

        await tag_service.update_tag(
            tag_id, transaction=mock_transaction, name="Trekking", user_id=TEST_USER_ID
        )

        (event,) = _published(mock_event_publisher)
        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

    @pytest.mark.asyncio
    async def test_rename_of_an_unassigned_tag_publishes_nothing(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        """No journal carries the tag, so no journal changed."""
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.find_by_name.return_value = None
        mock_tag_repo.get_journal_ids_for_tag.return_value = []
        mock_tag_repo.save.side_effect = lambda tag: tag

        await tag_service.update_tag(
            tag_id, transaction=mock_transaction, name="Trekking", user_id=TEST_USER_ID
        )

        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("color", "#123456"),
            ("description", "Outdoor entries"),
        ],
    )
    async def test_non_name_changes_publish_nothing(
        self,
        tag_service,
        mock_tag_repo,
        mock_event_publisher,
        mock_transaction,
        field,
        value,
    ):
        """Colour and description do not alter any journal, so no history."""
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.get_journal_ids_for_tag.return_value = [7]
        mock_tag_repo.save.side_effect = lambda tag: tag

        await tag_service.update_tag(
            tag_id, transaction=mock_transaction, **{field: value}, user_id=TEST_USER_ID
        )

        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reparenting_publishes_nothing(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        """A tag's position in the hierarchy is invisible on a journal."""
        tag_id = uuid4()
        parent_id = uuid4()
        mock_tag_repo.find_by_id.side_effect = lambda requested, *, user_id: {
            tag_id: JournalTag(user_id=TEST_USER_ID, id=tag_id, name="Hiking"),
            parent_id: JournalTag(user_id=TEST_USER_ID, id=parent_id, name="Outdoors"),
        }.get(requested)
        mock_tag_repo.get_journal_ids_for_tag.return_value = [7]
        mock_tag_repo.save.side_effect = lambda tag: tag

        await tag_service.update_tag(
            tag_id,
            transaction=mock_transaction,
            parent_id=parent_id,
            user_id=TEST_USER_ID,
        )

        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resending_the_same_name_publishes_nothing(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        """update_tag returns early with no changes; nothing was renamed."""
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.get_journal_ids_for_tag.return_value = [7]

        await tag_service.update_tag(
            tag_id, transaction=mock_transaction, name="Hiking", user_id=TEST_USER_ID
        )

        mock_tag_repo.save.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_name_rejected_by_the_pre_check_publishes_nothing(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        """A duplicate name aborts before the write, so nothing is published."""
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.find_by_name.return_value = JournalTag(
            user_id=TEST_USER_ID, id=uuid4(), name="Trekking"
        )
        mock_tag_repo.get_journal_ids_for_tag.return_value = [7]

        with pytest.raises(JournalValidationError):
            await tag_service.update_tag(
                tag_id,
                transaction=mock_transaction,
                name="Trekking",
                user_id=TEST_USER_ID,
            )

        mock_tag_repo.save.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_write_rejected_by_the_constraint_publishes_nothing(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        """The publish sits after the write, so a rejected write cannot reach it.

        This is the case the ordering exists for: the uniqueness pre-check passes
        and only the ``UPDATE`` fails, on a name a concurrent insert took in
        between. Moving the publish above the save would emit an event here for a
        rename that never happened — the transaction would roll the outbox row
        back with it, but the ordering is what makes that a non-question.
        """
        tag_id = uuid4()
        mock_tag_repo.find_by_id.return_value = JournalTag(
            user_id=TEST_USER_ID, id=tag_id, name="Hiking"
        )
        mock_tag_repo.find_by_name.return_value = None
        mock_tag_repo.get_journal_ids_for_tag.return_value = [7]
        mock_tag_repo.save.side_effect = IntegrityError(
            "uq_journal_tags_user_id_name_lower", {}, Exception("dup")
        )

        with pytest.raises(JournalValidationError):
            await tag_service.update_tag(
                tag_id,
                transaction=mock_transaction,
                name="Trekking",
                user_id=TEST_USER_ID,
            )

        mock_event_publisher.publish.assert_not_awaited()


class TestResolveFilterTagIds:
    """``resolve_filter_tag_ids`` turns tag names or ids into a subtree filter."""

    @staticmethod
    def _saved_tag(name: str) -> JournalTag:
        return JournalTag(user_id=TEST_USER_ID, id=uuid4(), name=name, color="#FF0000")

    @pytest.mark.asyncio
    async def test_uuids_pass_through(
        self, tag_service: JournalTagService, mock_tag_repo: AsyncMock
    ) -> None:
        tag_id = uuid4()
        mock_tag_repo.get_descendants_for_tags.return_value = []

        assert await tag_service.resolve_filter_tag_ids(
            [str(tag_id)], user_id=TEST_USER_ID
        ) == [str(tag_id)]
        mock_tag_repo.find_by_name.assert_not_called()

    @pytest.mark.asyncio
    async def test_names_are_resolved_to_ids(
        self, tag_service: JournalTagService, mock_tag_repo: AsyncMock
    ) -> None:
        hiking = self._saved_tag("hiking")
        mock_tag_repo.find_by_name.side_effect = lambda name, *, user_id: (
            hiking if name.lower() == "hiking" else None
        )
        mock_tag_repo.get_descendants_for_tags.return_value = []

        assert await tag_service.resolve_filter_tag_ids(
            [" Hiking "], user_id=TEST_USER_ID
        ) == [str(hiking.id)]

    @pytest.mark.asyncio
    async def test_descendant_tags_are_included(
        self, tag_service: JournalTagService, mock_tag_repo: AsyncMock
    ) -> None:
        outdoors = self._saved_tag("outdoors")
        climbing = self._saved_tag("climbing")
        mock_tag_repo.find_by_name.return_value = outdoors
        mock_tag_repo.get_descendants_for_tags.return_value = [climbing]

        resolved = await tag_service.resolve_filter_tag_ids(
            ["outdoors"], user_id=TEST_USER_ID
        )

        assert resolved is not None
        assert set(resolved) == {str(outdoors.id), str(climbing.id)}
        mock_tag_repo.get_descendants_for_tags.assert_awaited_once_with(
            [outdoors.id], user_id=TEST_USER_ID
        )

    @pytest.mark.asyncio
    async def test_unknown_name_is_an_error_not_a_silent_empty_filter(
        self, tag_service: JournalTagService, mock_tag_repo: AsyncMock
    ) -> None:
        """Dropping an unresolvable tag would widen the search without saying so."""
        mock_tag_repo.find_by_name.return_value = None

        with pytest.raises(
            ValueError,
            match=(
                r"^Unknown journal tag 'nonexistent-tag'\. Pass a tag name or id "
                r"from list_journal_tags\.$"
            ),
        ):
            await tag_service.resolve_filter_tag_ids(
                ["nonexistent-tag"], user_id=TEST_USER_ID
            )

    @pytest.mark.asyncio
    async def test_blank_input_means_no_filter(
        self, tag_service: JournalTagService, mock_tag_repo: AsyncMock
    ) -> None:
        assert (
            await tag_service.resolve_filter_tag_ids([], user_id=TEST_USER_ID) is None
        )
        assert (
            await tag_service.resolve_filter_tag_ids(["  ", ""], user_id=TEST_USER_ID)
            is None
        )
        mock_tag_repo.get_descendants_for_tags.assert_not_called()


class TestEveryOperationIsScopedToTheActingUser:
    """Another user's tag reads as a missing one; lookups carry the owner."""

    @staticmethod
    def _foreign_tag(mock_tag_repo) -> JournalTag:
        theirs = JournalTag(user_id=OTHER_USER_ID, id=uuid4(), name="theirs")

        async def find_by_id(tag_id, *, user_id):
            return _owned_by(theirs if tag_id == theirs.id else None, user_id)

        mock_tag_repo.find_by_id.side_effect = find_by_id
        return theirs

    @pytest.mark.asyncio
    async def test_a_foreign_tag_cannot_be_updated(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        theirs = self._foreign_tag(mock_tag_repo)

        with pytest.raises(JournalTagNotFoundError):
            await tag_service.update_tag(
                theirs.id, mock_transaction, user_id=TEST_USER_ID, name="mine now"
            )

        mock_tag_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_foreign_tag_cannot_be_deleted(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        theirs = self._foreign_tag(mock_tag_repo)

        with pytest.raises(JournalTagNotFoundError):
            await tag_service.delete_tag(
                theirs.id, mock_transaction, user_id=TEST_USER_ID
            )

        mock_tag_repo.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_foreign_tag_cannot_be_assigned(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        theirs = self._foreign_tag(mock_tag_repo)

        with pytest.raises(JournalTagNotFoundError):
            await tag_service.assign_tag(
                7, theirs.id, mock_transaction, user_id=TEST_USER_ID
            )

        mock_tag_repo.assign_tag.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_removing_a_foreign_tag_is_a_no_op(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        theirs = self._foreign_tag(mock_tag_repo)

        await tag_service.remove_tag(
            7, theirs.id, mock_transaction, user_id=TEST_USER_ID
        )

        mock_tag_repo.remove_tag.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_foreign_merge_target_is_not_found(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        mine = JournalTag(user_id=TEST_USER_ID, id=uuid4(), name="mine")
        theirs = JournalTag(user_id=OTHER_USER_ID, id=uuid4(), name="theirs")
        by_id = {mine.id: mine, theirs.id: theirs}

        async def find_by_id(tag_id, *, user_id):
            return _owned_by(by_id.get(tag_id), user_id)

        mock_tag_repo.find_by_id.side_effect = find_by_id

        with pytest.raises(JournalTagNotFoundError):
            await tag_service.merge_tag(
                mine.id, theirs.id, mock_transaction, user_id=TEST_USER_ID
            )

        mock_tag_repo.merge_into.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_filter_names_and_descendants_resolve_within_the_owner(
        self, tag_service, mock_tag_repo
    ):
        mock_tag_repo.find_by_name.return_value = JournalTag(
            user_id=TEST_USER_ID, id=uuid4(), name="family"
        )
        mock_tag_repo.get_descendants_for_tags.return_value = []

        await tag_service.resolve_filter_tag_ids(["family"], user_id=TEST_USER_ID)

        mock_tag_repo.find_by_name.assert_awaited_once_with(
            "family", user_id=TEST_USER_ID
        )
        assert mock_tag_repo.get_descendants_for_tags.await_args.kwargs == {
            "user_id": TEST_USER_ID
        }

    @pytest.mark.asyncio
    async def test_a_foreign_id_in_the_filter_is_kept_so_it_matches_nothing(
        self, tag_service, mock_tag_repo
    ):
        """Dropping it would leave no filter at all, and widen the search."""
        foreign_id = str(uuid4())
        mock_tag_repo.get_descendants_for_tags.return_value = []

        assert await tag_service.resolve_filter_tag_ids(
            [foreign_id], user_id=TEST_USER_ID
        ) == [foreign_id]


class TestCreateTagParent:
    """A new tag's parent must be one of the same owner's tags."""

    @pytest.mark.asyncio
    async def test_a_foreign_parent_is_not_found(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        mock_tag_repo.find_by_id.return_value = None
        foreign_parent = uuid4()
        tag = JournalTag(user_id=TEST_USER_ID, name="child", parent_id=foreign_parent)

        with pytest.raises(JournalTagNotFoundError):
            await tag_service.create_tag(tag, transaction=mock_transaction)

        mock_tag_repo.find_by_id.assert_awaited_once_with(
            foreign_parent, user_id=TEST_USER_ID
        )
        mock_tag_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_owned_parent_is_accepted(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        parent = JournalTag(user_id=TEST_USER_ID, id=uuid4(), name="parent")
        mock_tag_repo.find_by_id.return_value = parent
        tag = JournalTag(user_id=TEST_USER_ID, name="child", parent_id=parent.id)
        mock_tag_repo.save.return_value = tag

        assert await tag_service.create_tag(tag, transaction=mock_transaction) is tag


class TestATagGoneMidWriteIsNotFound:
    """A tag deleted between the check and the write publishes nothing.

    The repository reports that its guarded write changed nothing; the service
    then raises, so the unit of work rolls back instead of committing history
    events for a change that did not happen.
    """

    @pytest.mark.asyncio
    async def test_a_merge_that_changed_nothing_raises_and_publishes_nothing(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        source = JournalTag(user_id=TEST_USER_ID, id=uuid4(), name="source")
        target = JournalTag(user_id=TEST_USER_ID, id=uuid4(), name="target")
        by_id = {source.id: source, target.id: target}

        async def find_by_id(tag_id, *, user_id):
            return _owned_by(by_id.get(tag_id), user_id)

        mock_tag_repo.find_by_id.side_effect = find_by_id
        mock_tag_repo.get_journal_ids_for_tag.return_value = [7]
        mock_tag_repo.merge_into.return_value = False

        with pytest.raises(JournalTagNotFoundError):
            await tag_service.merge_tag(
                source.id, target.id, mock_transaction, user_id=TEST_USER_ID
            )

        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_delete_that_changed_nothing_raises_and_publishes_nothing(
        self, tag_service, mock_tag_repo, mock_event_publisher, mock_transaction
    ):
        tag = JournalTag(user_id=TEST_USER_ID, id=uuid4(), name="doomed")
        mock_tag_repo.find_by_id.return_value = tag
        mock_tag_repo.get_journal_ids_for_tag.return_value = [7]
        mock_tag_repo.delete.return_value = False

        with pytest.raises(JournalTagNotFoundError):
            await tag_service.delete_tag(tag.id, mock_transaction, user_id=TEST_USER_ID)

        mock_event_publisher.publish.assert_not_awaited()
