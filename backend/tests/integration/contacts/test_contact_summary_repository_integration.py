"""Integration tests for ContactSummaryRepository with real database."""

import pytest
from core_shared.models.contacts.entities import (
    Contact,
    ContactSummary,
    SummaryDisabledReason,
    SummaryStatus,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import (
    SqlContactRepository,
    SqlContactSummaryRepository,
)
from tests.integration.contact_seeding import TEST_USER_ID


@pytest.mark.integration
class TestContactSummaryRepositoryIntegration:
    """Integration tests for ContactSummaryRepository with real database."""

    @pytest.fixture
    def contact_repo(self, clean_database: AsyncConnection):
        """Create ContactRepository instance."""
        return SqlContactRepository(clean_database)

    @pytest.fixture
    def summary_repo(self, clean_database: AsyncConnection):
        """Create ContactSummaryRepository instance."""
        return SqlContactSummaryRepository(clean_database)

    @pytest.fixture
    async def test_contact(self, contact_repo: SqlContactRepository) -> Contact:
        """Create and return a test contact."""
        contact = Contact(user_id=TEST_USER_ID, first_name="Summary", last_name="Test")
        saved: Contact = await contact_repo.save(contact)
        return saved

    @pytest.mark.asyncio
    async def test_find_by_contact_id_returns_none_when_no_summary(
        self, summary_repo, test_contact
    ):
        """Test finding summary for contact with no summary returns None."""
        result = await summary_repo.find_by_contact_id(test_contact.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_creates_new_summary(self, summary_repo, test_contact):
        """Test creating a new summary via upsert."""
        summary = ContactSummary(
            contact_id=test_contact.id,
            summary_text="Test summary text",
            follow_up_suggestions=["Call them", "Send email"],
            status=SummaryStatus.GENERATED,
        )

        result = await summary_repo.upsert(summary)

        assert result.id is not None
        assert result.contact_id == test_contact.id
        assert result.summary_text == "Test summary text"
        assert result.follow_up_suggestions == ["Call them", "Send email"]
        assert result.status == SummaryStatus.GENERATED
        assert result.created_at is not None
        assert result.updated_at is not None

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_summary(self, summary_repo, test_contact):
        """Test updating an existing summary via upsert."""
        # Create initial summary
        initial = ContactSummary(
            contact_id=test_contact.id,
            summary_text="Initial text",
            status=SummaryStatus.PENDING,
        )
        await summary_repo.upsert(initial)

        # Update via upsert
        updated = ContactSummary(
            contact_id=test_contact.id,
            summary_text="Updated text",
            follow_up_suggestions=["Follow up"],
            status=SummaryStatus.GENERATED,
        )
        result = await summary_repo.upsert(updated)

        assert result.summary_text == "Updated text"
        assert result.follow_up_suggestions == ["Follow up"]
        assert result.status == SummaryStatus.GENERATED

    @pytest.mark.asyncio
    async def test_find_by_contact_id_returns_summary(self, summary_repo, test_contact):
        """Test finding an existing summary by contact ID."""
        summary = ContactSummary(
            contact_id=test_contact.id,
            summary_text="Findable summary",
            follow_up_suggestions=["Suggestion 1"],
            status=SummaryStatus.GENERATED,
            is_disabled=False,
            is_user_override=True,
            user_override_text="User text",
        )
        await summary_repo.upsert(summary)

        result = await summary_repo.find_by_contact_id(test_contact.id)

        assert result is not None
        assert result.summary_text == "Findable summary"
        assert result.follow_up_suggestions == ["Suggestion 1"]
        assert result.status == SummaryStatus.GENERATED
        assert result.is_user_override is True
        assert result.user_override_text == "User text"

    @pytest.mark.asyncio
    async def test_update_status(self, summary_repo, test_contact):
        """Test updating summary status."""
        summary = ContactSummary(
            contact_id=test_contact.id,
            summary_text="Status test",
            status=SummaryStatus.PENDING,
        )
        await summary_repo.upsert(summary)

        result = await summary_repo.update_status(
            test_contact.id, SummaryStatus.GENERATING.value
        )

        assert result is not None
        assert result.status == SummaryStatus.GENERATING
        assert result.summary_text == "Status test"

    @pytest.mark.asyncio
    async def test_update_status_nonexistent_returns_none(self, summary_repo):
        """Test updating status for nonexistent contact returns None."""
        result = await summary_repo.update_status(99999, SummaryStatus.PENDING.value)
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_disabled_summary(self, summary_repo, test_contact):
        """Test creating a disabled summary."""
        summary = ContactSummary(
            contact_id=test_contact.id,
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.USER,
        )
        result = await summary_repo.upsert(summary)

        assert result.is_disabled is True
        assert result.status == SummaryStatus.DISABLED

    @pytest.mark.asyncio
    async def test_disabled_reason_round_trips(self, summary_repo, test_contact):
        """The disabled reason is persisted and read back on every read path."""
        await summary_repo.upsert(
            ContactSummary(
                contact_id=test_contact.id,
                status=SummaryStatus.DISABLED,
                is_disabled=True,
                disabled_reason=SummaryDisabledReason.LOW_ACTIVITY,
            )
        )

        found = await summary_repo.find_by_contact_id(test_contact.id)
        updated = await summary_repo.update_status(
            test_contact.id, SummaryStatus.DISABLED.value
        )

        assert found is not None
        assert found.disabled_reason == SummaryDisabledReason.LOW_ACTIVITY
        assert updated is not None
        assert updated.disabled_reason == SummaryDisabledReason.LOW_ACTIVITY

    @pytest.mark.asyncio
    async def test_upsert_clears_disabled_reason_on_enable(
        self, summary_repo, test_contact
    ):
        """Re-upserting an enabled summary clears the stored reason."""
        await summary_repo.upsert(
            ContactSummary(
                contact_id=test_contact.id,
                status=SummaryStatus.DISABLED,
                is_disabled=True,
                disabled_reason=SummaryDisabledReason.USER,
            )
        )

        await summary_repo.upsert(
            ContactSummary(contact_id=test_contact.id, status=SummaryStatus.PENDING)
        )

        found = await summary_repo.find_by_contact_id(test_contact.id)
        assert found is not None
        assert found.is_disabled is False
        assert found.disabled_reason is None

    @pytest.mark.asyncio
    async def test_contact_load_includes_disabled_reason(
        self, contact_repo, summary_repo, test_contact
    ):
        """The contact aggregate's summary carries the disabled reason."""
        await summary_repo.upsert(
            ContactSummary(
                contact_id=test_contact.id,
                status=SummaryStatus.DISABLED,
                is_disabled=True,
                disabled_reason=SummaryDisabledReason.USER,
            )
        )

        contact = await contact_repo.find_by_id(test_contact.id)

        assert contact is not None
        assert contact.summary is not None
        assert contact.summary.disabled_reason == SummaryDisabledReason.USER

    async def _holds_summary_row_lock(self, connection: AsyncConnection) -> bool:
        """Whether this connection holds a row lock (SELECT ... FOR UPDATE) on
        contact_summaries. Only a locking read takes RowShareLock on the table;
        plain reads take AccessShareLock and writes RowExclusiveLock."""
        result = await connection.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_locks
                    WHERE pid = pg_backend_pid()
                      AND relation = 'contact_summaries'::regclass
                      AND mode = 'RowShareLock'
                )
                """
            )
        )
        held: bool = result.scalar_one()
        return held

    @pytest.mark.asyncio
    async def test_find_for_update_locks_the_row(
        self, summary_repo, test_contact, clean_database
    ):
        """A read made to be written back locks the row until the transaction ends."""
        await summary_repo.upsert(ContactSummary(contact_id=test_contact.id))

        found = await summary_repo.find_by_contact_id(test_contact.id, for_update=True)

        assert found is not None
        assert await self._holds_summary_row_lock(clean_database) is True

    @pytest.mark.asyncio
    async def test_plain_find_takes_no_row_lock(
        self, summary_repo, test_contact, clean_database
    ):
        """An ordinary read does not lock the row."""
        await summary_repo.upsert(ContactSummary(contact_id=test_contact.id))

        found = await summary_repo.find_by_contact_id(test_contact.id)

        assert found is not None
        assert await self._holds_summary_row_lock(clean_database) is False

    @pytest.mark.asyncio
    async def test_guarded_upsert_skips_a_user_disabled_row(
        self, summary_repo, test_contact
    ):
        """An automated write never overwrites a summary the user disabled."""
        await summary_repo.upsert(
            ContactSummary(
                contact_id=test_contact.id,
                summary_text="Old text",
                status=SummaryStatus.DISABLED,
                is_disabled=True,
                disabled_reason=SummaryDisabledReason.USER,
            )
        )

        written = await summary_repo.upsert_from_generation(
            ContactSummary(
                contact_id=test_contact.id,
                summary_text="AI text",
                status=SummaryStatus.GENERATED,
            )
        )

        assert written is None
        found = await summary_repo.find_by_contact_id(test_contact.id)
        assert found is not None
        assert found.disabled_reason == SummaryDisabledReason.USER
        assert found.summary_text == "Old text"

    @pytest.mark.asyncio
    async def test_guarded_upsert_writes_over_an_auto_paused_row(
        self, summary_repo, test_contact
    ):
        """A low-activity pause is not the user's choice, so it can be lifted."""
        await summary_repo.upsert(
            ContactSummary(
                contact_id=test_contact.id,
                status=SummaryStatus.DISABLED,
                is_disabled=True,
                disabled_reason=SummaryDisabledReason.LOW_ACTIVITY,
            )
        )

        written = await summary_repo.upsert_from_generation(
            ContactSummary(
                contact_id=test_contact.id,
                summary_text="AI text",
                status=SummaryStatus.GENERATED,
            )
        )

        assert written is not None
        assert written.id is not None
        found = await summary_repo.find_by_contact_id(test_contact.id)
        assert found is not None
        assert found.is_disabled is False
        assert found.summary_text == "AI text"

    @pytest.mark.asyncio
    async def test_guarded_upsert_inserts_a_missing_row(
        self, summary_repo, test_contact
    ):
        """With no row yet, the guarded write creates one."""
        written = await summary_repo.upsert_from_generation(
            ContactSummary(contact_id=test_contact.id, summary_text="First")
        )

        assert written is not None
        found = await summary_repo.find_by_contact_id(test_contact.id)
        assert found is not None
        assert found.summary_text == "First"

    @pytest.mark.asyncio
    async def test_generation_upsert_keeps_user_override_fields(
        self, summary_repo, test_contact
    ):
        """A generation write never overwrites the user's override text, even
        when the generator's copy of the row predates the override."""
        await summary_repo.upsert(
            ContactSummary(
                contact_id=test_contact.id,
                is_user_override=True,
                user_override_text="My own summary",
                status=SummaryStatus.GENERATED,
            )
        )

        written = await summary_repo.upsert_from_generation(
            ContactSummary(
                contact_id=test_contact.id,
                summary_text="AI text",
                status=SummaryStatus.GENERATED,
            )
        )

        assert written is not None
        assert written.summary_text == "AI text"
        assert written.is_user_override is True
        assert written.user_override_text == "My own summary"
        found = await summary_repo.find_by_contact_id(test_contact.id)
        assert found is not None
        assert found.is_user_override is True
        assert found.user_override_text == "My own summary"

    @pytest.mark.asyncio
    async def test_guarded_status_update_skips_a_user_disabled_row(
        self, summary_repo, test_contact
    ):
        """GENERATING is never written onto a summary the user disabled."""
        await summary_repo.upsert(
            ContactSummary(
                contact_id=test_contact.id,
                status=SummaryStatus.DISABLED,
                is_disabled=True,
                disabled_reason=SummaryDisabledReason.USER,
            )
        )

        updated = await summary_repo.update_status_unless_user_disabled(
            test_contact.id, SummaryStatus.GENERATING.value
        )

        assert updated is None
        found = await summary_repo.find_by_contact_id(test_contact.id)
        assert found is not None
        assert found.status == SummaryStatus.DISABLED

    @pytest.mark.asyncio
    async def test_guarded_status_update_changes_an_enabled_row(
        self, summary_repo, test_contact
    ):
        """An enabled summary moves to GENERATING as before."""
        await summary_repo.upsert(ContactSummary(contact_id=test_contact.id))

        updated = await summary_repo.update_status_unless_user_disabled(
            test_contact.id, SummaryStatus.GENERATING.value
        )

        assert updated is not None
        assert updated.status == SummaryStatus.GENERATING

    @pytest.mark.asyncio
    async def test_disabled_row_without_reason_is_rejected(
        self, test_contact, clean_database
    ):
        """The database refuses a disabled flag with no recorded reason."""
        with pytest.raises(IntegrityError):
            async with clean_database.begin_nested():
                await clean_database.execute(
                    text(
                        """
                        INSERT INTO contact_summaries (contact_id, status, is_disabled)
                        VALUES (:contact_id, 'disabled', TRUE)
                        """
                    ),
                    {"contact_id": test_contact.id},
                )

    @pytest.mark.asyncio
    async def test_contact_find_by_id_includes_summary(
        self, contact_repo, summary_repo, test_contact
    ):
        """Test that find_by_id on ContactRepository loads the summary."""
        summary = ContactSummary(
            contact_id=test_contact.id,
            summary_text="Loaded with contact",
            follow_up_suggestions=["Check in"],
            status=SummaryStatus.GENERATED,
        )
        await summary_repo.upsert(summary)

        contact = await contact_repo.find_by_id(test_contact.id)

        assert contact is not None
        assert contact.summary is not None
        assert contact.summary.summary_text == "Loaded with contact"
        assert contact.summary.follow_up_suggestions == ["Check in"]
        assert contact.summary.status == SummaryStatus.GENERATED

    @pytest.mark.asyncio
    async def test_contact_find_by_id_without_summary(self, contact_repo, test_contact):
        """Test that find_by_id works when no summary exists."""
        contact = await contact_repo.find_by_id(test_contact.id)

        assert contact is not None
        assert contact.summary is None

    @pytest.mark.asyncio
    async def test_summary_deleted_with_contact(
        self, contact_repo, summary_repo, test_contact
    ):
        """Test that summary is cascade-deleted when contact is deleted."""
        summary = ContactSummary(
            contact_id=test_contact.id,
            summary_text="Will be deleted",
            status=SummaryStatus.GENERATED,
        )
        await summary_repo.upsert(summary)

        # Delete the contact
        await contact_repo.delete(test_contact.id)

        # Summary should also be gone
        result = await summary_repo.find_by_contact_id(test_contact.id)
        assert result is None
