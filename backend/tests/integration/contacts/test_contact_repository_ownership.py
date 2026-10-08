"""A contact owned by another user is invisible to every aggregate-level read.

Each test seeds the acting user's contact and a *foreign* one that matches the
same query just as well (same name, tag, favourite flag, a link from the same
integration), so the owner filter is the only thing that can tell them apart.
An absent id would prove nothing.
"""

import pytest
from core_shared.models.contacts.entities import (
    Contact,
    ContactMethod,
    MethodType,
    Tag,
)
from core_shared.models.contacts.value_objects import TagName
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import SqlContactRepository, SqlTagRepository
from app.core.contacts.models.exceptions import ContactNotFoundError
from tests.integration.contact_seeding import OTHER_USER_ID, TEST_USER_ID

OWN_EMAIL = "sarah@own.example"
FOREIGN_EMAIL = "sarah@foreign.example"
FOREIGN_EXTERNAL_ID = "people/c-foreign"


async def _save_contact(
    repo: SqlContactRepository, *, user_id: str, email: str, tag: Tag
) -> int:
    saved = await repo.save(
        Contact(
            user_id=user_id, first_name="Sarah", last_name="Connor", is_favourite=True
        )
    )
    assert saved.id is not None
    assert tag.id is not None
    await repo.add_method(
        saved.id,
        ContactMethod(
            method_type=MethodType.EMAIL,
            value=email,
            contact_id=saved.id,
            is_primary=True,
        ),
    )
    await repo.assign_tag(saved.id, tag.id)
    return saved.id


async def _link(
    connection: AsyncConnection, contact_id: int, external_id: str, *, user_id: str
) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO sync_metadata (
                user_id, internal_id, integration_source, external_id,
                last_synced_at, version_hash, sync_status, retry_count,
                internal_entity_type, external_entity_type, created_at, updated_at
            ) VALUES (
                :uid, :iid, 'google', :eid, now(), 'h', 'success', 0,
                'contact', 'person', now(), now()
            )
            """
        ),
        {"uid": user_id, "iid": contact_id, "eid": external_id},
    )


async def _contact_rows(connection: AsyncConnection, contact_id: int) -> int:
    result = await connection.execute(
        text("SELECT COUNT(*) FROM contacts WHERE id = :id"), {"id": contact_id}
    )
    return int(result.scalar_one())


@pytest.mark.integration
class TestContactRepositoryOwnership:
    """The owner-scoped aggregate reads and writes of ``SqlContactRepository``."""

    @pytest.fixture
    def repo(self, clean_database: AsyncConnection) -> SqlContactRepository:
        return SqlContactRepository(clean_database)

    @pytest.fixture
    async def tag(self, clean_database: AsyncConnection) -> Tag:
        return await SqlTagRepository(clean_database).save(Tag(name=TagName("crew")))

    @pytest.fixture
    async def own_id(self, repo: SqlContactRepository, tag: Tag) -> int:
        return await _save_contact(repo, user_id=TEST_USER_ID, email=OWN_EMAIL, tag=tag)

    @pytest.fixture
    async def foreign_id(
        self, repo: SqlContactRepository, tag: Tag, clean_database: AsyncConnection
    ) -> int:
        contact_id = await _save_contact(
            repo, user_id=OTHER_USER_ID, email=FOREIGN_EMAIL, tag=tag
        )
        await _link(
            clean_database, contact_id, FOREIGN_EXTERNAL_ID, user_id=OTHER_USER_ID
        )
        return contact_id

    async def test_find_by_id_returns_none_for_a_foreign_contact(
        self, repo: SqlContactRepository, own_id: int, foreign_id: int
    ) -> None:
        assert await repo.find_by_id(foreign_id, user_id=TEST_USER_ID) is None
        found = await repo.find_by_id(own_id, user_id=TEST_USER_ID)
        assert found is not None
        assert found.id == own_id

    async def test_contact_exists_is_false_for_a_foreign_contact(
        self, repo: SqlContactRepository, own_id: int, foreign_id: int
    ) -> None:
        assert await repo.contact_exists(foreign_id, user_id=TEST_USER_ID) is False
        assert await repo.contact_exists(own_id, user_id=TEST_USER_ID) is True

    async def test_find_names_by_ids_omits_a_foreign_contact(
        self, repo: SqlContactRepository, own_id: int, foreign_id: int
    ) -> None:
        names = await repo.find_names_by_ids([own_id, foreign_id], user_id=TEST_USER_ID)
        assert set(names) == {own_id}

    async def test_find_by_email_misses_a_foreign_contact(
        self, repo: SqlContactRepository, own_id: int, foreign_id: int
    ) -> None:
        assert await repo.find_by_email(FOREIGN_EMAIL, user_id=TEST_USER_ID) is None
        found = await repo.find_by_email(OWN_EMAIL, user_id=TEST_USER_ID)
        assert found is not None
        assert found.id == own_id

    async def test_find_by_external_reference_misses_a_foreign_contact(
        self, repo: SqlContactRepository, foreign_id: int
    ) -> None:
        assert (
            await repo.find_by_external_reference(
                "google", FOREIGN_EXTERNAL_ID, user_id=TEST_USER_ID
            )
            is None
        )
        found = await repo.find_by_external_reference(
            "google", FOREIGN_EXTERNAL_ID, user_id=OTHER_USER_ID
        )
        assert found is not None
        assert found.id == foreign_id

    async def test_find_by_external_reference_ignores_another_owners_link(
        self, repo: SqlContactRepository, own_id: int, clean_database: AsyncConnection
    ) -> None:
        """A link is the owner's: another user's link row naming this user's
        contact id (a mis-owned row) does not resolve to the contact."""
        await _link(clean_database, own_id, "people/c-misowned", user_id=OTHER_USER_ID)

        assert (
            await repo.find_by_external_reference(
                "google", "people/c-misowned", user_id=TEST_USER_ID
            )
            is None
        )

    async def test_search_excludes_a_foreign_contact(
        self, repo: SqlContactRepository, own_id: int, foreign_id: int
    ) -> None:
        results = await repo.search("Sarah", user_id=TEST_USER_ID)
        assert [c.id for c in results] == [own_id]

    async def test_get_all_excludes_a_foreign_contact(
        self, repo: SqlContactRepository, own_id: int, foreign_id: int
    ) -> None:
        results = await repo.get_all(user_id=TEST_USER_ID)
        assert [c.id for c in results] == [own_id]

    async def test_get_count_ignores_a_foreign_contact(
        self, repo: SqlContactRepository, own_id: int, foreign_id: int
    ) -> None:
        assert await repo.get_count(user_id=TEST_USER_ID) == 1

    @pytest.mark.parametrize(
        ("is_favourite", "by_tag"),
        [
            pytest.param(True, False, id="favourite"),
            pytest.param(None, True, id="tag"),
            pytest.param(True, True, id="both"),
        ],
    )
    async def test_filtered_reads_exclude_a_foreign_contact(
        self,
        repo: SqlContactRepository,
        tag: Tag,
        own_id: int,
        foreign_id: int,
        is_favourite: bool | None,
        by_tag: bool,
    ) -> None:
        assert tag.id is not None
        tag_ids = [tag.id] if by_tag else None
        listed = await repo.get_contacts_by_filters(
            is_favourite=is_favourite, tag_ids=tag_ids, user_id=TEST_USER_ID
        )
        counted = await repo.get_contacts_count_by_filters(
            is_favourite=is_favourite, tag_ids=tag_ids, user_id=TEST_USER_ID
        )
        assert [c.id for c in listed] == [own_id]
        assert counted == 1

    async def test_delete_refuses_a_foreign_contact_and_leaves_it(
        self,
        repo: SqlContactRepository,
        foreign_id: int,
        clean_database: AsyncConnection,
    ) -> None:
        with pytest.raises(ContactNotFoundError):
            await repo.delete(foreign_id, user_id=TEST_USER_ID)
        assert await _contact_rows(clean_database, foreign_id) == 1

    async def test_bulk_delete_all_leaves_a_foreign_contact(
        self,
        repo: SqlContactRepository,
        own_id: int,
        foreign_id: int,
        clean_database: AsyncConnection,
    ) -> None:
        await repo.bulk_delete_all(clean_database, user_id=TEST_USER_ID)
        assert await _contact_rows(clean_database, own_id) == 0
        assert await _contact_rows(clean_database, foreign_id) == 1

    async def test_find_owner_id_names_the_owner(
        self, repo: SqlContactRepository, own_id: int, foreign_id: int
    ) -> None:
        assert await repo.find_owner_id(own_id) == TEST_USER_ID
        assert await repo.find_owner_id(foreign_id) == OTHER_USER_ID

    async def test_find_owner_id_is_none_for_a_missing_contact(
        self, repo: SqlContactRepository
    ) -> None:
        assert await repo.find_owner_id(2_000_000_000) is None
