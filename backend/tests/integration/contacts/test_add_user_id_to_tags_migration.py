"""Migration round-trip test for 0135 (contact tags gain an owner).

``tags`` had no ``user_id``. 0135 adds the column, gives each tag the owner of
the contacts that carry it — a tag no contact carries goes to the site's one
user, derived from the data exactly as 0127 does for journal tags — and then
requires it. Each branch:

- a tag carried by one owner's contacts -> that owner, whatever the site owner;
- an uncarried tag -> the site's one real owner (how that owner is derived is
  ``owner_derivation``'s, tested with ``0127``);
- a tag carried by two owners' contacts -> refuses, naming the tag;
- a tag under another owner's tag -> refuses, naming both, including an
  uncarried parent the override gives another owner than its child's;
- uncarried tags and no owner evidence -> refuses unless ``-x tags_owner``;
- no tags -> nothing to assign; the revision upgrades and downgrades.

Runs against an isolated throwaway database so the shared session DB is untouched.
Rows are inserted raw because the schema is pinned at 0134.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import (
    RunAlembic,
    columns,
    execute,
    index_exists,
    load_revision,
    tables_with_column,
)

migration = load_revision("0135_add_user_id_to_tags.py")

REAL_OWNER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"
OTHER_REAL_OWNER = "11111111-2222-4333-8444-555555555555"

_PREVIOUS_REVISION = "0134"
_REVISION = "0135"


async def _seed_tags(url: str, *names: str) -> None:
    for name in names:
        await execute(url, "INSERT INTO tags (name) VALUES (:name)", {"name": name})


async def _seed_child_tag(url: str, name: str, parent: str) -> None:
    await execute(
        url,
        "INSERT INTO tags (name, parent_id) SELECT :name, id FROM tags WHERE name = :parent",
        {"name": name, "parent": parent},
    )


async def _seed_contact(url: str, owner: str, *tag_names: str) -> None:
    """Seed a contact owned by ``owner`` carrying the named (existing) tags."""
    await execute(
        url,
        """
        WITH contact AS (
            INSERT INTO contacts (user_id, first_name)
            VALUES (:owner, 'Seeded')
            RETURNING id
        )
        INSERT INTO contact_tags (contact_id, tag_id)
        SELECT contact.id, t.id
        FROM contact CROSS JOIN tags t
        WHERE t.name = ANY(:tag_names)
        """,
        {"owner": owner, "tag_names": list(tag_names)},
    )


async def _seed_settings(url: str, owner: str) -> None:
    await execute(
        url, "INSERT INTO user_settings (user_id) VALUES (:owner)", {"owner": owner}
    )


async def _tag_owners(url: str) -> dict[str, str | None]:
    """Return ``{name: user_id}`` for every contact tag."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(text("SELECT name, user_id FROM tags"))
            ).fetchall()
            return {str(row.name): row.user_id for row in rows}
    finally:
        await engine.dispose()


async def _user_id_is_nullable(url: str) -> bool:
    return bool(
        await execute(
            url,
            """
            SELECT is_nullable = 'YES' FROM information_schema.columns
            WHERE table_name = 'tags' AND column_name = 'user_id'
            """,
        )
    )


@pytest.mark.integration
@pytest.mark.slow
class TestAddUserIdToTags:
    """0135 gives each contact tag its carriers' owner, or the site's one user."""

    async def test_every_table_recording_a_user_is_evidence(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The evidence is exactly the tables that hold a ``user_id`` at 0134."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)

        assert await tables_with_column(url, "user_id") == set(
            migration.EVIDENCE_TABLES
        )

    async def test_a_carried_tag_goes_to_its_contacts_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The carriers decide, even against a different site-wide owner."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tags(url, "family", "work")
        await _seed_contact(url, REAL_OWNER, "family")
        await _seed_contact(url, OTHER_REAL_OWNER, "work")
        await _seed_contact(url, OTHER_REAL_OWNER, "work")

        run_alembic(url, "upgrade", _REVISION)

        assert await _tag_owners(url) == {
            "family": REAL_OWNER,
            "work": OTHER_REAL_OWNER,
        }
        assert await index_exists(url, "idx_tags_user_id")
        assert not await _user_id_is_nullable(url)

    async def test_an_uncarried_tag_goes_to_the_site_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tags(url, "family", "unused")
        await _seed_child_tag(url, "family/kids", "family")
        await _seed_contact(url, REAL_OWNER, "family/kids")

        run_alembic(url, "upgrade", _REVISION)

        assert await _tag_owners(url) == {
            "family": REAL_OWNER,
            "family/kids": REAL_OWNER,
            "unused": REAL_OWNER,
        }

    async def test_a_tag_carried_by_two_owners_refuses_and_names_it(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """Either owner would leave the other's contact holding a foreign tag."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tags(url, "shared", "family")
        await _seed_contact(url, REAL_OWNER, "shared", "family")
        await _seed_contact(url, OTHER_REAL_OWNER, "shared")

        with pytest.raises(RuntimeError, match="shared") as excinfo:
            run_alembic(url, "upgrade", _REVISION, x_args={"tags_owner": REAL_OWNER})

        assert "family" not in str(excinfo.value)
        assert "user_id" not in await columns(url, "tags")

    async def test_a_tag_under_another_owners_tag_refuses_and_names_both(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """Parent and child must share an owner, or one sees the other's tree."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tags(url, "family")
        await _seed_child_tag(url, "family/kids", "family")
        await _seed_contact(url, REAL_OWNER, "family")
        await _seed_contact(url, OTHER_REAL_OWNER, "family/kids")

        with pytest.raises(RuntimeError, match="family/kids") as excinfo:
            run_alembic(url, "upgrade", _REVISION)

        assert "'family'" in str(excinfo.value)
        assert "user_id" not in await columns(url, "tags")

    async def test_an_uncarried_parent_given_another_owner_than_its_child_refuses(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The site owner the override names for a parent is checked against its
        child's carriers too: the hierarchy refusal runs after every tag has one."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tags(url, "family")
        await _seed_child_tag(url, "family/kids", "family")
        await _seed_contact(url, OTHER_REAL_OWNER, "family/kids")

        with pytest.raises(RuntimeError, match="family/kids"):
            run_alembic(url, "upgrade", _REVISION, x_args={"tags_owner": REAL_OWNER})

        assert "user_id" not in await columns(url, "tags")

    async def test_uncarried_tags_without_owner_evidence_refuse(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tags(url, "unused")

        with pytest.raises(RuntimeError, match="tags_owner"):
            run_alembic(url, "upgrade", _REVISION)

        assert "user_id" not in await columns(url, "tags")

    async def test_the_operator_override_resolves_an_ambiguous_site_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The override names the owner of uncarried tags; carried tags keep theirs."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tags(url, "family", "unused")
        await _seed_contact(url, REAL_OWNER, "family")
        await _seed_settings(url, OTHER_REAL_OWNER)

        with pytest.raises(RuntimeError, match="tags_owner"):
            run_alembic(url, "upgrade", _REVISION)

        run_alembic(url, "upgrade", _REVISION, x_args={"tags_owner": OTHER_REAL_OWNER})

        assert await _tag_owners(url) == {
            "family": REAL_OWNER,
            "unused": OTHER_REAL_OWNER,
        }

    async def test_an_empty_database_upgrades_and_downgrades(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """No tags means nothing to assign — even with no owner evidence."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)
        assert "user_id" in await columns(url, "tags")

        run_alembic(url, "downgrade", _PREVIOUS_REVISION)
        assert "user_id" not in await columns(url, "tags")
        assert not await index_exists(url, "idx_tags_user_id")

        run_alembic(url, "upgrade", _REVISION)
