"""Migration round-trip test for 0092 (dedupe bug-created duplicate contacts).

Verifies the data migration that merges the duplicate contacts produced by the
Immich -> Google -> Immich loop before ``external_references`` is dropped:

- the bug shape (email-less Immich-linked **A** + email-less Google-linked **B**
  with the same normalised name **and** the same full-precision birthday) collapses
  to a single contact: B is merged into the survivor A, which afterwards holds
  **both** the Immich and Google links and carries B's re-pointed sub-entities;
- a non-duplicate contact with an email is left untouched;
- a legitimately email-less Google contact that shares the name but has a different
  birthday (or no birthday) is left untouched (over-merge guard);
- an ambiguous name (two survivors share one source candidate) is **not** merged
  (over-merge protection);
- orphaned ``sync_metadata`` links (internal entity gone) are reconciled;
- the merge is idempotent (downgrade to 0091 + re-upgrade is a no-op);
- a dry-run (``-x dedupe_dry_run=true``) makes no changes;
- the threshold guard (``-x dedupe_max=0``) aborts unless ``dedupe_force=true``.

Runs against an isolated throwaway database so the shared session DB is untouched.
"""

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Row, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

_BACKEND_DIR = Path(__file__).resolve().parents[3]


def _run_alembic_x(
    database_url: str, command: str, target: str, x_args: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``alembic [-x k=v ...] <command> <target>`` and return the result.

    Unlike the shared ``run_alembic`` fixture this exposes ``-x`` arguments (for
    the dry-run / threshold-guard paths) and returns the process so the caller can
    assert on success *or* failure.
    """
    cmd = [sys.executable, "-m", "alembic"]
    for key, value in (x_args or {}).items():
        cmd += ["-x", f"{key}={value}"]
    cmd += [command, target]
    return subprocess.run(
        cmd,
        cwd=str(_BACKEND_DIR),
        capture_output=True,
        text=True,
        env={**os.environ, "ENVIRONMENT": "test", "DATABASE_URL": database_url},
    )


async def _insert_contact(conn: AsyncConnection, first: str, last: str) -> int:
    row = (
        await conn.execute(
            text(
                "INSERT INTO contacts (first_name, last_name) "
                "VALUES (:first, :last) RETURNING id"
            ),
            {"first": first, "last": last},
        )
    ).fetchone()
    assert row is not None
    return int(row.id)


async def _link(
    conn: AsyncConnection,
    contact_id: int,
    source: str,
    external_id: str,
) -> None:
    await conn.execute(
        text("""
            INSERT INTO sync_metadata
                (internal_id, integration_source, external_id, last_synced_at,
                 version_hash, sync_status, internal_entity_type, external_entity_type)
            VALUES (:iid, :source, :eid, now(), 'h', 'success', 'contact', 'person')
        """),
        {"iid": contact_id, "source": source, "eid": external_id},
    )


async def _add_email(conn: AsyncConnection, contact_id: int, value: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO contact_methods (contact_id, method_type, value, is_primary) "
            "VALUES (:cid, 'email', :v, true)"
        ),
        {"cid": contact_id, "v": value},
    )


async def _add_birthday(
    conn: AsyncConnection, contact_id: int, year: int, month: int, day: int
) -> None:
    await conn.execute(
        text(
            "INSERT INTO contact_important_dates "
            "(contact_id, date_type, precision, year, month, day) "
            "VALUES (:cid, 'birthday', 'full', :y, :m, :d)"
        ),
        {"cid": contact_id, "y": year, "m": month, "d": day},
    )


async def _seed(engine_url: str) -> dict[str, int]:
    """Seed the bug-shaped and control data at the 0091 schema. Returns key ids."""
    engine = create_async_engine(engine_url)
    ids: dict[str, int] = {}
    try:
        async with engine.begin() as conn:
            # Bug pair: A (immich, email-less) + B (google, email-less), same name
            # AND same full-precision birthday (the discriminator).
            ids["survivor"] = await _insert_contact(conn, "John", "Smith")
            ids["source"] = await _insert_contact(conn, "John", "Smith")
            await _link(conn, ids["survivor"], "immich", "immich-person-1")
            await _link(conn, ids["source"], "google", "people/c_dup")
            await _add_birthday(conn, ids["survivor"], 1990, 5, 6)
            await _add_birthday(conn, ids["source"], 1990, 5, 6)
            # B carries data that must survive the merge onto A.
            await conn.execute(
                text(
                    "INSERT INTO contact_methods (contact_id, method_type, value, "
                    "is_primary) VALUES (:cid, 'phone', '+61400000000', true)"
                ),
                {"cid": ids["source"]},
            )
            await conn.execute(
                text(
                    "INSERT INTO contact_notes (contact_id, content) "
                    "VALUES (:cid, 'met at conference')"
                ),
                {"cid": ids["source"]},
            )

            # Control 1: a Google contact named John Smith but WITH an email — not
            # email-less, so it must never be merged.
            ids["with_email"] = await _insert_contact(conn, "John", "Smith")
            await _link(conn, ids["with_email"], "google", "people/c_email")
            await _add_email(conn, ids["with_email"], "john@example.com")

            # Control 2: a *legitimately* email-less Google contact (e.g. phone-only)
            # that happens to share the survivor's name but has a DIFFERENT birthday
            # — must NOT be merged (the over-merge guard the birthday match provides).
            ids["diff_birthday"] = await _insert_contact(conn, "John", "Smith")
            await _link(conn, ids["diff_birthday"], "google", "people/c_diff")
            await _add_birthday(conn, ids["diff_birthday"], 1975, 1, 1)

            # Control 3: an email-less Google contact sharing the name but with NO
            # birthday at all — also must NOT be merged (no birthday to corroborate).
            ids["no_birthday"] = await _insert_contact(conn, "John", "Smith")
            await _link(conn, ids["no_birthday"], "google", "people/c_nobd")

            # Control 4: a distinct, untouched contact.
            ids["unrelated"] = await _insert_contact(conn, "Jane", "Doe")
            await _link(conn, ids["unrelated"], "google", "people/c_jane")
            await _add_email(conn, ids["unrelated"], "jane@example.com")

            # Ambiguous trio: two immich email-less "Sam Lee" + one google
            # email-less "Sam Lee", all sharing one birthday -> 2 survivors / 1
            # source for that (name, birthday) key -> skipped.
            ids["amb_a1"] = await _insert_contact(conn, "Sam", "Lee")
            ids["amb_a2"] = await _insert_contact(conn, "Sam", "Lee")
            ids["amb_b"] = await _insert_contact(conn, "Sam", "Lee")
            await _link(conn, ids["amb_a1"], "immich", "immich-sam-1")
            await _link(conn, ids["amb_a2"], "immich", "immich-sam-2")
            await _link(conn, ids["amb_b"], "google", "people/c_sam")
            await _add_birthday(conn, ids["amb_a1"], 1988, 8, 8)
            await _add_birthday(conn, ids["amb_a2"], 1988, 8, 8)
            await _add_birthday(conn, ids["amb_b"], 1988, 8, 8)

            # Orphan link: a contact link whose contact no longer exists.
            await conn.execute(
                text("""
                    INSERT INTO sync_metadata
                        (internal_id, integration_source, external_id, last_synced_at,
                         version_hash, sync_status, internal_entity_type,
                         external_entity_type)
                    VALUES (9000001, 'google', 'people/c_orphan', now(), 'h',
                            'success', 'contact', 'person')
                """)
            )
    finally:
        await engine.dispose()
    return ids


async def _links_for(engine_url: str, contact_id: int) -> set[str]:
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT integration_source FROM sync_metadata "
                        "WHERE internal_entity_type = 'contact' AND internal_id = :cid"
                    ),
                    {"cid": contact_id},
                )
            ).fetchall()
            return {r.integration_source for r in rows}
    finally:
        await engine.dispose()


async def _scalar(engine_url: str, sql: str, params: dict[str, Any]) -> Any:
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar()
    finally:
        await engine.dispose()


async def _all(engine_url: str, sql: str, params: dict[str, Any]) -> Sequence[Row[Any]]:
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).fetchall()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestDedupeBugCreatedContactsMigration:
    """0092 dedupe of bug-created duplicate contacts."""

    async def test_merges_bug_pair_and_is_idempotent(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        run_alembic(url, "upgrade", "0091")
        ids = await _seed(url)
        run_alembic(url, "upgrade", "0092")

        # 1. The bug pair collapsed to the survivor; the source is gone.
        survivors = await _all(
            url,
            "SELECT id FROM contacts WHERE lower(first_name) = 'john' "
            "AND lower(last_name) = 'smith' "
            "AND id IN (:a, :b)",
            {"a": ids["survivor"], "b": ids["source"]},
        )
        assert [r.id for r in survivors] == [ids["survivor"]]
        assert (
            await _scalar(
                url,
                "SELECT count(*) FROM contacts WHERE id = :id",
                {"id": ids["source"]},
            )
            == 0
        )

        # 2. The survivor now holds BOTH links (the fix's end state).
        assert await _links_for(url, ids["survivor"]) == {"immich", "google"}

        # 3. The source's sub-entities re-pointed onto the survivor.
        assert (
            await _scalar(
                url,
                "SELECT count(*) FROM contact_notes WHERE contact_id = :id "
                "AND content = 'met at conference'",
                {"id": ids["survivor"]},
            )
            == 1
        )
        assert (
            await _scalar(
                url,
                "SELECT count(*) FROM contact_methods WHERE contact_id = :id "
                "AND method_type = 'phone'",
                {"id": ids["survivor"]},
            )
            == 1
        )
        assert (
            await _scalar(
                url,
                "SELECT count(*) FROM contact_important_dates WHERE contact_id = :id "
                "AND date_type = 'birthday'",
                {"id": ids["survivor"]},
            )
            == 1
        )

        # 4. The email-bearing same-name contact and the unrelated contact survive.
        assert (
            await _scalar(
                url,
                "SELECT count(*) FROM contacts WHERE id = :id",
                {"id": ids["with_email"]},
            )
            == 1
        )
        assert await _links_for(url, ids["with_email"]) == {"google"}
        assert (
            await _scalar(
                url,
                "SELECT count(*) FROM contacts WHERE id = :id",
                {"id": ids["unrelated"]},
            )
            == 1
        )

        # 4b. Email-less Google same-name contacts that do NOT corroborate on
        #     birthday (different birthday / no birthday) are left untouched — the
        #     guard against over-merging legitimately email-less Google contacts.
        for key in ("diff_birthday", "no_birthday"):
            assert (
                await _scalar(
                    url,
                    "SELECT count(*) FROM contacts WHERE id = :id",
                    {"id": ids[key]},
                )
                == 1
            )
            assert await _links_for(url, ids[key]) == {"google"}

        # 5. The ambiguous "Sam Lee" trio is left untouched (no guessing).
        for key in ("amb_a1", "amb_a2", "amb_b"):
            assert (
                await _scalar(
                    url,
                    "SELECT count(*) FROM contacts WHERE id = :id",
                    {"id": ids[key]},
                )
                == 1
            )

        # 6. The orphaned contact link was reconciled away.
        assert (
            await _scalar(
                url,
                "SELECT count(*) FROM sync_metadata WHERE external_id = 'people/c_orphan'",
                {},
            )
            == 0
        )

        # 7. Idempotent: downgrade (no-op) then re-upgrade changes nothing.
        run_alembic(url, "downgrade", "0091")
        run_alembic(url, "upgrade", "0092")
        assert await _links_for(url, ids["survivor"]) == {"immich", "google"}
        assert (
            await _scalar(
                url,
                "SELECT count(*) FROM contacts WHERE id = :id",
                {"id": ids["source"]},
            )
            == 0
        )

    async def test_dry_run_makes_no_changes(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        run_alembic(url, "upgrade", "0091")
        ids = await _seed(url)

        result = _run_alembic_x(url, "upgrade", "0092", {"dedupe_dry_run": "true"})
        assert result.returncode == 0, result.stderr

        # Both contacts still exist; no link moved onto the survivor.
        assert (
            await _scalar(
                url,
                "SELECT count(*) FROM contacts WHERE id = :id",
                {"id": ids["source"]},
            )
            == 1
        )
        assert await _links_for(url, ids["survivor"]) == {"immich"}
        assert await _links_for(url, ids["source"]) == {"google"}
        # Dry-run skips orphan reconciliation too.
        assert (
            await _scalar(
                url,
                "SELECT count(*) FROM sync_metadata WHERE external_id = 'people/c_orphan'",
                {},
            )
            == 1
        )

    async def test_threshold_guard_aborts_without_force(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        run_alembic(url, "upgrade", "0091")
        ids = await _seed(url)

        # One real pair exceeds a max of 0 -> abort, no changes.
        blocked = _run_alembic_x(url, "upgrade", "0092", {"dedupe_max": "0"})
        assert blocked.returncode != 0
        assert (
            await _scalar(
                url,
                "SELECT count(*) FROM contacts WHERE id = :id",
                {"id": ids["source"]},
            )
            == 1
        )

        # With force the same run proceeds and merges.
        forced = _run_alembic_x(
            url, "upgrade", "0092", {"dedupe_max": "0", "dedupe_force": "true"}
        )
        assert forced.returncode == 0, forced.stderr
        assert await _links_for(url, ids["survivor"]) == {"immich", "google"}
