"""Unit tests for ContactMergeService (ITER13-001 Phases 1 & 2).

Phase 1 covers the merge preconditions and that the service delegates the
relationship and journal-link re-points to the repositories. Phase 2 completes
the engine: sub-entity re-points, the prefer-non-empty scalar policy, source
deletion, the inline ``merged_from`` history row, and the survivor summary
refresh event. The REST/MCP surface arrives in later phases.
"""

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.contacts.entities import Contact
from core_shared.models.history import Provenance

from app.core.contacts.models.exceptions import (
    ContactMergeConflictError,
    ContactNotFoundError,
)
from app.core.contacts.services.contact_merge_service import ContactMergeService
from tests.integration.contact_seeding import TEST_USER_ID

SURVIVOR_ID = 1
SOURCE_ID = 2
SURVIVOR_OWNER = "survivor-owner"


@pytest.fixture
def mock_transaction() -> AsyncMock:
    mock_tx = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_result.fetchone.return_value = None
    mock_tx.execute.return_value = mock_result
    return mock_tx


@pytest.fixture
def survivor() -> Contact:
    return Contact(id=SURVIVOR_ID, first_name="Survivor", user_id=SURVIVOR_OWNER)


@pytest.fixture
def source() -> Contact:
    return Contact(user_id=TEST_USER_ID, id=SOURCE_ID, first_name="Source")


@pytest.fixture
def mock_contact_repo(mock_transaction, survivor, source) -> AsyncMock:
    repo = AsyncMock()
    repo.transaction = mock_transaction
    repo.find_by_id.side_effect = lambda cid, *, user_id: (
        survivor if cid == SURVIVOR_ID else source if cid == SOURCE_ID else None
    )
    # save() echoes the contact it was handed so callers can inspect the merge.
    repo.save.side_effect = lambda contact: contact
    return repo


@pytest.fixture
def mock_relationship_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_journal_rel_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_event_publisher() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_history_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.repoint_entity_history.return_value = 0
    repo.repoint_contact_task_history.return_value = 0
    return repo


@pytest.fixture
def mock_sync_metadata_repo() -> AsyncMock:
    repo = AsyncMock()
    # Default: no external links to reconcile.
    repo.repoint_contact_links.return_value = []
    return repo


@pytest.fixture
def mock_task_merge_service() -> AsyncMock:
    """The tasks domain's half of the merge (ITER18-006 Phase 1).

    A double rather than the real service because what the merge owes the tasks
    domain is a *call*, in the right place: the row work and the events it
    publishes are that service's own tests, and this file has no business
    knowing that ``task_contacts`` exists.
    """
    return AsyncMock()


@pytest.fixture
def merge_service(
    mock_contact_repo,
    mock_relationship_repo,
    mock_journal_rel_repo,
    mock_event_publisher,
    mock_history_repo,
    mock_sync_metadata_repo,
    mock_task_merge_service,
) -> ContactMergeService:
    return ContactMergeService(
        contact_repo=mock_contact_repo,
        relationship_repo=mock_relationship_repo,
        journal_relationship_repo=mock_journal_rel_repo,
        event_publisher=mock_event_publisher,
        history_repo=mock_history_repo,
        sync_metadata_repo=mock_sync_metadata_repo,
        task_merge_service=mock_task_merge_service,
    )


class TestContactMergePreconditions:
    """Validation of the merge preconditions."""

    @pytest.mark.asyncio
    async def test_self_merge_raises_conflict(
        self, merge_service, mock_transaction
    ) -> None:
        with pytest.raises(ContactMergeConflictError):
            await merge_service.merge_contacts(
                SURVIVOR_ID,
                SURVIVOR_ID,
                transaction=mock_transaction,
                user_id=TEST_USER_ID,
            )

    @pytest.mark.asyncio
    async def test_missing_survivor_raises_not_found(
        self, merge_service, mock_contact_repo, mock_transaction
    ) -> None:
        mock_contact_repo.find_by_id.side_effect = lambda cid, *, user_id: (
            None
            if cid == 999
            else Contact(user_id=TEST_USER_ID, id=cid, first_name="Source")
        )
        with pytest.raises(ContactNotFoundError):
            await merge_service.merge_contacts(
                999, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
            )

    @pytest.mark.asyncio
    async def test_missing_source_raises_not_found(
        self, merge_service, mock_contact_repo, mock_transaction
    ) -> None:
        mock_contact_repo.find_by_id.side_effect = lambda cid, *, user_id: (
            Contact(user_id=TEST_USER_ID, id=cid, first_name="Survivor")
            if cid == SURVIVOR_ID
            else None
        )
        with pytest.raises(ContactNotFoundError):
            await merge_service.merge_contacts(
                SURVIVOR_ID, 999, transaction=mock_transaction, user_id=TEST_USER_ID
            )


class TestContactMergeDelegation:
    """The service delegates the re-points to the repositories."""

    @pytest.mark.asyncio
    async def test_repoints_relationships_and_journal_links(
        self,
        merge_service,
        mock_relationship_repo,
        mock_journal_rel_repo,
        mock_transaction,
        survivor,
    ) -> None:
        result = await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        mock_relationship_repo.repoint_contact.assert_awaited_once_with(
            SOURCE_ID, SURVIVOR_ID, mock_transaction
        )
        mock_journal_rel_repo.repoint_contact.assert_awaited_once_with(
            SOURCE_ID, SURVIVOR_ID, mock_transaction
        )
        assert result is survivor

    @pytest.mark.asyncio
    async def test_repoints_every_sub_entity_then_deletes_source(
        self,
        merge_service,
        mock_contact_repo,
        mock_transaction,
    ) -> None:
        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        for repoint in (
            mock_contact_repo.repoint_methods,
            mock_contact_repo.repoint_addresses,
            mock_contact_repo.repoint_notes,
            mock_contact_repo.repoint_important_dates,
            mock_contact_repo.repoint_tags,
        ):
            repoint.assert_awaited_once_with(SOURCE_ID, SURVIVOR_ID, mock_transaction)

        # The source is deleted only after the aggregate has been re-pointed.
        mock_contact_repo.delete.assert_awaited_once_with(
            SOURCE_ID, user_id=TEST_USER_ID
        )

    @pytest.mark.asyncio
    async def test_repoints_history_then_deletes_source(
        self,
        merge_service,
        mock_contact_repo,
        mock_history_repo,
        mock_transaction,
    ) -> None:
        """The source's top-level history is re-pointed onto the survivor within
        the merge, after the sub-entities move and before the source row is
        deleted."""
        manager = MagicMock()
        manager.attach_mock(mock_history_repo.repoint_entity_history, "repoint")
        manager.attach_mock(mock_contact_repo.delete, "delete")

        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        mock_history_repo.repoint_entity_history.assert_awaited_once_with(
            SOURCE_ID, SURVIVOR_ID, "contact", mock_transaction
        )
        # The re-point must run before the source row is deleted.
        ordered = [call[0] for call in manager.mock_calls]
        assert ordered.index("repoint") < ordered.index("delete")

    @pytest.mark.asyncio
    async def test_repoints_task_records_then_deletes_source(
        self,
        merge_service,
        mock_contact_repo,
        mock_history_repo,
        mock_transaction,
    ) -> None:
        """The absorbed contact's task records move too (ITER18-006 Phase 2).

        A second call beside the one above, and it is not a duplicate of it: the
        two address disjoint row sets by different columns. ``entity_type =
        'contact'`` rows are found by ``entity_id`` and cannot name a task; a
        person's task records live on the *task* and name the person only in
        ``field_name``, so no widening of the first statement could ever reach
        them.

        Ordered against the delete for the same reason as every other re-point
        in this merge: once the source row is gone the merge has lost the id it
        would have searched for.
        """
        manager = MagicMock()
        manager.attach_mock(
            mock_history_repo.repoint_contact_task_history, "repoint_tasks"
        )
        manager.attach_mock(mock_contact_repo.delete, "delete")

        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        mock_history_repo.repoint_contact_task_history.assert_awaited_once_with(
            SOURCE_ID, SURVIVOR_ID, mock_transaction
        )
        ordered = [call[0] for call in manager.mock_calls]
        assert ordered.index("repoint_tasks") < ordered.index("delete")

    @pytest.mark.asyncio
    async def test_repoints_task_contact_links(
        self,
        merge_service,
        mock_task_merge_service,
        mock_transaction,
    ) -> None:
        """A merge carries a task's people with it (ITER18-006 Phase 1).

        The tasks domain performs the move and announces it; the contacts domain
        asks for it. Delegating rather than writing ``task_contacts`` here is
        what keeps the contacts domain from constructing task events.
        """
        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        mock_task_merge_service.repoint_contact_links.assert_awaited_once_with(
            source_contact_id=SOURCE_ID,
            survivor_contact_id=SURVIVOR_ID,
            transaction=mock_transaction,
            source=Provenance.SYSTEM,
            changed_by="system",
        )

    @pytest.mark.asyncio
    async def test_the_merging_actor_reaches_the_tasks_that_moved(
        self,
        merge_service,
        mock_task_merge_service,
        mock_transaction,
    ) -> None:
        """A merge is something a person did, and so are its consequences.

        Filing the moved tasks under ``system`` would tell that user's own
        history that part of what they did was not theirs — the same reasoning
        the journal merge's re-point records.
        """
        await merge_service.merge_contacts(
            SURVIVOR_ID,
            SOURCE_ID,
            transaction=mock_transaction,
            changed_by="user-1",
            source=Provenance.UI,
            user_id=TEST_USER_ID,
        )

        kwargs = mock_task_merge_service.repoint_contact_links.await_args.kwargs
        assert kwargs["source"] == Provenance.UI
        assert kwargs["changed_by"] == "user-1"

    @pytest.mark.asyncio
    async def test_repoints_task_links_then_deletes_source(
        self,
        merge_service,
        mock_contact_repo,
        mock_task_merge_service,
        mock_transaction,
    ) -> None:
        """The ordering *is* the fix.

        ``task_contacts.contact_id`` is ``ON DELETE CASCADE``, so a re-point
        after the delete has nothing left to move: the links are already gone,
        silently, which is the defect this phase repairs. Only the order
        separates the fix from the bug, so only an assertion on the order can
        stop it regressing.
        """
        manager = MagicMock()
        manager.attach_mock(
            mock_task_merge_service.repoint_contact_links, "repoint_tasks"
        )
        manager.attach_mock(mock_contact_repo.delete, "delete")

        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        ordered = [call[0] for call in manager.mock_calls]
        assert ordered.index("repoint_tasks") < ordered.index("delete")


class TestContactMergeScalarPolicy:
    """Prefer-non-empty scalar policy (survivor wins on conflict)."""

    @staticmethod
    def _saved_contact(mock_contact_repo: AsyncMock) -> Contact:
        mock_contact_repo.save.assert_awaited_once()
        return cast(Contact, mock_contact_repo.save.await_args.args[0])

    @pytest.mark.asyncio
    async def test_survivor_value_kept_when_source_empty(
        self, merge_service, mock_contact_repo, mock_transaction
    ) -> None:
        mock_contact_repo.find_by_id.side_effect = lambda cid, *, user_id: (
            Contact(
                user_id=TEST_USER_ID,
                id=SURVIVOR_ID,
                first_name="Survivor",
                company="Acme",
            )
            if cid == SURVIVOR_ID
            else Contact(
                user_id=TEST_USER_ID, id=SOURCE_ID, first_name="Source", company=None
            )
        )

        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        saved = self._saved_contact(mock_contact_repo)
        assert saved.id == SURVIVOR_ID
        assert saved.company == "Acme"

    @pytest.mark.asyncio
    async def test_source_value_used_when_survivor_empty(
        self, merge_service, mock_contact_repo, mock_transaction
    ) -> None:
        mock_contact_repo.find_by_id.side_effect = lambda cid, *, user_id: (
            Contact(
                user_id=TEST_USER_ID,
                id=SURVIVOR_ID,
                first_name="Survivor",
                job_title=None,
            )
            if cid == SURVIVOR_ID
            else Contact(
                user_id=TEST_USER_ID,
                id=SOURCE_ID,
                first_name="Source",
                job_title="Engineer",
            )
        )

        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        saved = self._saved_contact(mock_contact_repo)
        assert saved.job_title == "Engineer"

    @pytest.mark.asyncio
    async def test_survivor_wins_when_both_differ(
        self, merge_service, mock_contact_repo, mock_transaction
    ) -> None:
        mock_contact_repo.find_by_id.side_effect = lambda cid, *, user_id: (
            Contact(
                user_id=TEST_USER_ID,
                id=SURVIVOR_ID,
                first_name="Survivor",
                last_name="Keep",
            )
            if cid == SURVIVOR_ID
            else Contact(
                user_id=TEST_USER_ID,
                id=SOURCE_ID,
                first_name="Source",
                last_name="Drop",
            )
        )

        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        saved = self._saved_contact(mock_contact_repo)
        assert saved.first_name == "Survivor"
        assert saved.last_name == "Keep"

    @pytest.mark.parametrize("foreign_id", [SURVIVOR_ID, SOURCE_ID])
    @pytest.mark.asyncio
    async def test_a_foreign_contact_is_not_found_and_nothing_merges(
        self,
        merge_service,
        mock_contact_repo,
        mock_task_merge_service,
        mock_event_publisher,
        mock_transaction,
        foreign_id: int,
    ) -> None:
        """Either side belonging to another user reads as missing (404, not 403)."""
        mock_contact_repo.find_by_id.side_effect = lambda cid, *, user_id: (
            Contact(user_id=user_id, id=cid, first_name="Mine")
            if user_id == TEST_USER_ID and cid != foreign_id
            else None
        )

        with pytest.raises(ContactNotFoundError):
            await merge_service.merge_contacts(
                SURVIVOR_ID,
                SOURCE_ID,
                transaction=mock_transaction,
                user_id=TEST_USER_ID,
            )

        assert all(
            call.kwargs["user_id"] == TEST_USER_ID
            for call in mock_contact_repo.find_by_id.await_args_list
        )
        mock_contact_repo.delete.assert_not_awaited()
        mock_contact_repo.save.assert_not_awaited()
        assert mock_task_merge_service.method_calls == []
        mock_event_publisher.publish.assert_not_awaited()


class TestContactMergeOwner:
    """A merge keeps the survivor's owner; it never adopts the source's."""

    @pytest.mark.asyncio
    async def test_the_merged_contact_keeps_the_survivors_owner(
        self, merge_service, mock_contact_repo, mock_transaction
    ) -> None:
        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        saved = cast(Contact, mock_contact_repo.save.await_args.args[0])
        assert saved.user_id == SURVIVOR_OWNER

    @pytest.mark.asyncio
    async def test_merge_events_name_the_survivors_owner(
        self, merge_service, mock_event_publisher, mock_transaction
    ) -> None:
        """Workers reconcile a merge only in the owner's accounts."""
        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        owners = {
            call.args[0].event_type: call.args[0].event_data.get("user_id")
            for call in mock_event_publisher.publish.call_args_list
            if call.args[0].event_type in ("ContactMerged", "ContactUpdated")
        }
        assert owners == {
            "ContactMerged": SURVIVOR_OWNER,
            "ContactUpdated": SURVIVOR_OWNER,
        }


class TestContactMergeSideEffects:
    """The merge publishes a ContactUpdated audit event and a summary refresh.

    ITER12-003 Phase 2: the inline ``merged_from`` audit row is now produced by
    the history projection from a published ``ContactUpdated`` event rather than a
    synchronous history write.
    """

    @pytest.mark.asyncio
    async def test_publishes_merged_from_history_event(
        self,
        merge_service,
        mock_event_publisher,
        mock_transaction,
    ) -> None:
        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        published = [c.args[0] for c in mock_event_publisher.publish.await_args_list]
        merged_events = [e for e in published if e.event_type == "ContactUpdated"]
        assert len(merged_events) == 1
        event = merged_events[0]
        assert event.aggregate_id == SURVIVOR_ID
        changed_fields = event.event_data["changed_fields"]
        assert "merged_from" in changed_fields
        old_value, new_value = changed_fields["merged_from"]
        assert old_value == SOURCE_ID
        assert new_value == SURVIVOR_ID

    @staticmethod
    def _published(mock_event_publisher: AsyncMock) -> dict[str, Any]:
        """Map each published event by its ``event_type``."""
        return {
            call.args[0].event_type: call.args[0]
            for call in mock_event_publisher.publish.await_args_list
        }

    @pytest.mark.asyncio
    async def test_requests_summary_refresh_for_survivor(
        self,
        merge_service,
        mock_event_publisher,
        mock_transaction,
    ) -> None:
        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        event = self._published(mock_event_publisher)["ContactSummaryRefreshRequested"]
        assert event.aggregate_id == SURVIVOR_ID

    @pytest.mark.asyncio
    async def test_emits_contact_merged_event_with_provenance(
        self,
        merge_service,
        mock_event_publisher,
        mock_transaction,
    ) -> None:
        await merge_service.merge_contacts(
            SURVIVOR_ID,
            SOURCE_ID,
            transaction=mock_transaction,
            changed_by="ui",
            source=Provenance.UI,
            user_id=TEST_USER_ID,
        )

        event = self._published(mock_event_publisher)["ContactMerged"]
        assert event.aggregate_id == SURVIVOR_ID
        assert event.event_data["survivor_contact_id"] == SURVIVOR_ID
        assert event.event_data["source_contact_id"] == SOURCE_ID
        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"

    @pytest.mark.asyncio
    async def test_does_not_emit_contact_deleted_for_source(
        self,
        merge_service,
        mock_event_publisher,
        mock_transaction,
    ) -> None:
        """The merge must NOT emit ``ContactDeleted`` for the source.

        Integration workers (e.g. the Google worker) consume ``ContactDeleted``
        to delete the *remote* contact unconditionally — that contradicts merge
        semantics, where the source's external links may need to carry over to
        or consolidate onto the survivor (ITER13-005). Search de-indexing of the
        source is handled by the search indexer's ``ContactMerged`` handler
        instead, which has no integration side effects.
        """
        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        published = self._published(mock_event_publisher)
        assert "ContactDeleted" not in published
        assert "ContactMerged" in published


class TestContactMergeExternalReferences:
    """ITER13-005 Phase 1: the merge re-points the source's external links.

    The local re-point of the canonical ``sync_metadata`` links runs inline in the
    merge transaction (a local ``UPDATE``/``DELETE``, never a remote call).
    Same-service collisions surfaced by the re-point are carried on the
    ``ContactMerged`` event so the integration workers (Phases 2/3) can reconcile
    the remote records after the source's local row has gone.
    """

    @staticmethod
    def _published(mock_event_publisher: AsyncMock) -> dict[str, Any]:
        return {
            call.args[0].event_type: call.args[0]
            for call in mock_event_publisher.publish.await_args_list
        }

    @pytest.mark.asyncio
    async def test_repoints_external_references_before_deleting_source(
        self,
        merge_service,
        mock_contact_repo,
        mock_sync_metadata_repo,
        mock_transaction,
    ) -> None:
        manager = MagicMock()
        manager.attach_mock(
            mock_sync_metadata_repo.repoint_contact_links, "repoint_refs"
        )
        manager.attach_mock(mock_contact_repo.delete, "delete")

        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        mock_sync_metadata_repo.repoint_contact_links.assert_awaited_once_with(
            SOURCE_ID, SURVIVOR_ID, mock_transaction
        )
        ordered = [call[0] for call in manager.mock_calls]
        assert ordered.index("repoint_refs") < ordered.index("delete")

    @pytest.mark.asyncio
    async def test_collisions_carried_on_contact_merged_event(
        self,
        merge_service,
        mock_event_publisher,
        mock_sync_metadata_repo,
        mock_transaction,
    ) -> None:
        from app.core.integrations.adapters.sql.sync_metadata_repository import (
            IntegrationLinkCollision,
        )

        collision = IntegrationLinkCollision(
            external_system="google",
            external_entity_type="person",
            source_external_id="people/source",
            survivor_external_id="people/survivor",
        )
        mock_sync_metadata_repo.repoint_contact_links.return_value = [collision]

        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        event = self._published(mock_event_publisher)["ContactMerged"]
        collisions = event.event_data["external_collisions"]
        assert collisions == [
            {
                "external_system": "google",
                "external_entity_type": "person",
                "source_external_id": "people/source",
                "survivor_external_id": "people/survivor",
            }
        ]

    @pytest.mark.asyncio
    async def test_no_collisions_yields_empty_payload(
        self,
        merge_service,
        mock_event_publisher,
        mock_transaction,
    ) -> None:
        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction, user_id=TEST_USER_ID
        )

        event = self._published(mock_event_publisher)["ContactMerged"]
        assert event.event_data["external_collisions"] == []


class TestContactMergeOverrides:
    """ITER13-002 Phase 1: per-field overrides (survivor / source / custom).

    An override is a mapping ``field_name -> explicit value to apply``. A present
    key wins over the ITER13-001 prefer-non-empty default; an absent key falls
    back to that default. The UI/agent resolves the "survivor vs source vs custom"
    choice into a concrete value before calling the service (mirroring the journal
    ``MergeResolutionDialog`` ↔ ``merge_journals`` contract).
    """

    @staticmethod
    def _saved_contact(mock_contact_repo: AsyncMock) -> Contact:
        mock_contact_repo.save.assert_awaited_once()
        return cast(Contact, mock_contact_repo.save.await_args.args[0])

    @staticmethod
    def _conflicting(mock_contact_repo: AsyncMock) -> None:
        """Both contacts hold differing non-empty values for every scalar field."""
        mock_contact_repo.find_by_id.side_effect = lambda cid, *, user_id: (
            Contact(
                user_id=TEST_USER_ID,
                id=SURVIVOR_ID,
                first_name="SurvFirst",
                last_name="SurvLast",
                middle_name="SurvMiddle",
                nick_name="SurvNick",
                company="SurvCo",
                job_title="SurvTitle",
                photo_url="https://survivor/photo.png",
                is_favourite=True,
            )
            if cid == SURVIVOR_ID
            else Contact(
                user_id=TEST_USER_ID,
                id=SOURCE_ID,
                first_name="SrcFirst",
                last_name="SrcLast",
                middle_name="SrcMiddle",
                nick_name="SrcNick",
                company="SrcCo",
                job_title="SrcTitle",
                photo_url="https://source/photo.png",
                is_favourite=False,
            )
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "field, custom_value",
        [
            ("first_name", "CustomFirst"),
            ("last_name", "CustomLast"),
            ("middle_name", "CustomMiddle"),
            ("nick_name", "CustomNick"),
            ("company", "CustomCo"),
            ("job_title", "CustomTitle"),
            ("photo_url", "https://custom/photo.png"),
        ],
    )
    async def test_custom_override_applied_per_field(
        self, merge_service, mock_contact_repo, mock_transaction, field, custom_value
    ) -> None:
        self._conflicting(mock_contact_repo)

        await merge_service.merge_contacts(
            SURVIVOR_ID,
            SOURCE_ID,
            transaction=mock_transaction,
            overrides={field: custom_value},
            user_id=TEST_USER_ID,
        )

        saved = self._saved_contact(mock_contact_repo)
        assert getattr(saved, field) == custom_value

    @pytest.mark.asyncio
    async def test_override_can_select_source_value_over_survivor(
        self, merge_service, mock_contact_repo, mock_transaction
    ) -> None:
        # Survivor is non-empty, so prefer-non-empty would keep it; the override
        # of the source's value must win, proving overrides beat survivor-wins.
        self._conflicting(mock_contact_repo)

        await merge_service.merge_contacts(
            SURVIVOR_ID,
            SOURCE_ID,
            transaction=mock_transaction,
            overrides={"company": "SrcCo"},
            user_id=TEST_USER_ID,
        )

        saved = self._saved_contact(mock_contact_repo)
        assert saved.company == "SrcCo"

    @pytest.mark.asyncio
    async def test_is_favourite_false_override_is_honoured(
        self, merge_service, mock_contact_repo, mock_transaction
    ) -> None:
        # Survivor is_favourite=True; an explicit False override must win even
        # though it is falsy (boolean edge case — distinguished from "absent").
        self._conflicting(mock_contact_repo)

        await merge_service.merge_contacts(
            SURVIVOR_ID,
            SOURCE_ID,
            transaction=mock_transaction,
            overrides={"is_favourite": False},
            user_id=TEST_USER_ID,
        )

        saved = self._saved_contact(mock_contact_repo)
        assert saved.is_favourite is False

    @pytest.mark.asyncio
    async def test_absent_override_falls_back_to_default_policy(
        self, merge_service, mock_contact_repo, mock_transaction
    ) -> None:
        self._conflicting(mock_contact_repo)

        # Only override company; every other field keeps survivor-wins default.
        await merge_service.merge_contacts(
            SURVIVOR_ID,
            SOURCE_ID,
            transaction=mock_transaction,
            overrides={"company": "CustomCo"},
            user_id=TEST_USER_ID,
        )

        saved = self._saved_contact(mock_contact_repo)
        assert saved.company == "CustomCo"
        assert saved.first_name == "SurvFirst"  # survivor wins by default
        assert saved.job_title == "SurvTitle"

    @pytest.mark.asyncio
    async def test_overridden_fields_recorded_in_audit_event(
        self, merge_service, mock_contact_repo, mock_event_publisher, mock_transaction
    ) -> None:
        self._conflicting(mock_contact_repo)

        await merge_service.merge_contacts(
            SURVIVOR_ID,
            SOURCE_ID,
            transaction=mock_transaction,
            overrides={"company": "CustomCo"},
            user_id=TEST_USER_ID,
        )

        published = [c.args[0] for c in mock_event_publisher.publish.await_args_list]
        updated = next(e for e in published if e.event_type == "ContactUpdated")
        changed_fields = updated.event_data["changed_fields"]
        assert "merged_from" in changed_fields
        # The explicitly overridden field is auditable as (old, new).
        assert "company" in changed_fields
        old_value, new_value = changed_fields["company"]
        assert old_value == "SurvCo"
        assert new_value == "CustomCo"


class TestHasScalarConflicts:
    """``has_scalar_conflicts`` mirrors ``has_base_conflicts`` for journals."""

    @pytest.mark.asyncio
    async def test_both_non_empty_and_differing_is_a_conflict(
        self, merge_service
    ) -> None:
        survivor = Contact(
            user_id=TEST_USER_ID, id=SURVIVOR_ID, first_name="Alice", company="Acme"
        )
        source = Contact(
            user_id=TEST_USER_ID, id=SOURCE_ID, first_name="Alice", company="Globex"
        )
        assert merge_service.has_scalar_conflicts(survivor, source) is True

    @pytest.mark.asyncio
    async def test_one_side_empty_is_not_a_conflict(self, merge_service) -> None:
        survivor = Contact(
            user_id=TEST_USER_ID, id=SURVIVOR_ID, first_name="Alice", company="Acme"
        )
        source = Contact(
            user_id=TEST_USER_ID, id=SOURCE_ID, first_name="Alice", company=None
        )
        assert merge_service.has_scalar_conflicts(survivor, source) is False

    @pytest.mark.asyncio
    async def test_equal_values_are_not_a_conflict(self, merge_service) -> None:
        survivor = Contact(
            user_id=TEST_USER_ID, id=SURVIVOR_ID, first_name="Alice", company="Acme"
        )
        source = Contact(
            user_id=TEST_USER_ID, id=SOURCE_ID, first_name="Alice", company="Acme"
        )
        assert merge_service.has_scalar_conflicts(survivor, source) is False

    @pytest.mark.asyncio
    async def test_both_empty_is_not_a_conflict(self, merge_service) -> None:
        survivor = Contact(
            user_id=TEST_USER_ID, id=SURVIVOR_ID, first_name="Alice", company=None
        )
        source = Contact(
            user_id=TEST_USER_ID, id=SOURCE_ID, first_name="Alice", company=None
        )
        assert merge_service.has_scalar_conflicts(survivor, source) is False
