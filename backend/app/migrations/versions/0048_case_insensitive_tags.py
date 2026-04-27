"""case_insensitive_tags

Revision ID: 0048
Revises: 0047
Create Date: 2026-04-27 15:02:12.114917

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Deduplicate `tags` ---

    # 1. First, delete contact_tags for the dropped tag if the contact already has the keep_tag
    op.execute("""
        WITH duplicates AS (
            SELECT lower(name) as lname, min(id) as keep_id
            FROM tags
            GROUP BY lower(name)
            HAVING count(*) > 1
        ),
        to_merge AS (
            SELECT t.id as drop_id, d.keep_id
            FROM tags t
            JOIN duplicates d ON lower(t.name) = d.lname AND t.id != d.keep_id
        )
        DELETE FROM contact_tags ct
        USING to_merge tm
        WHERE ct.tag_id = tm.drop_id
        AND EXISTS (
            SELECT 1 FROM contact_tags ct2
            WHERE ct2.contact_id = ct.contact_id
            AND ct2.tag_id = tm.keep_id
        );
    """)

    # 2. Update remaining contact_tags
    op.execute("""
        WITH duplicates AS (
            SELECT lower(name) as lname, min(id) as keep_id
            FROM tags
            GROUP BY lower(name)
            HAVING count(*) > 1
        ),
        to_merge AS (
            SELECT t.id as drop_id, d.keep_id
            FROM tags t
            JOIN duplicates d ON lower(t.name) = d.lname AND t.id != d.keep_id
        )
        UPDATE contact_tags ct
        SET tag_id = tm.keep_id
        FROM to_merge tm
        WHERE ct.tag_id = tm.drop_id;
    """)

    # 3. Update any tags that have a dropped tag as parent
    op.execute("""
        WITH duplicates AS (
            SELECT lower(name) as lname, min(id) as keep_id
            FROM tags
            GROUP BY lower(name)
            HAVING count(*) > 1
        ),
        to_merge AS (
            SELECT t.id as drop_id, d.keep_id
            FROM tags t
            JOIN duplicates d ON lower(t.name) = d.lname AND t.id != d.keep_id
        )
        UPDATE tags t
        SET parent_id = tm.keep_id
        FROM to_merge tm
        WHERE t.parent_id = tm.drop_id;
    """)

    # 4. Delete the duplicate tags
    op.execute("""
        WITH duplicates AS (
            SELECT lower(name) as lname, min(id) as keep_id
            FROM tags
            GROUP BY lower(name)
            HAVING count(*) > 1
        )
        DELETE FROM tags t
        USING duplicates d
        WHERE lower(t.name) = d.lname AND t.id != d.keep_id;
    """)

    # --- Deduplicate `journal_tags` ---

    # 1. First, delete journal_tag_assignments for the dropped tag if the journal already has the keep_tag
    op.execute("""
        WITH duplicates AS (
            SELECT lower(name) as lname, min(id::text)::uuid as keep_id
            FROM journal_tags
            GROUP BY lower(name)
            HAVING count(*) > 1
        ),
        to_merge AS (
            SELECT t.id as drop_id, d.keep_id
            FROM journal_tags t
            JOIN duplicates d ON lower(t.name) = d.lname AND t.id != d.keep_id
        )
        DELETE FROM journal_tag_assignments jta
        USING to_merge tm
        WHERE jta.tag_id = tm.drop_id
        AND EXISTS (
            SELECT 1 FROM journal_tag_assignments jta2
            WHERE jta2.journal_id = jta.journal_id
            AND jta2.tag_id = tm.keep_id
        );
    """)

    # 2. Update remaining journal_tag_assignments
    op.execute("""
        WITH duplicates AS (
            SELECT lower(name) as lname, min(id::text)::uuid as keep_id
            FROM journal_tags
            GROUP BY lower(name)
            HAVING count(*) > 1
        ),
        to_merge AS (
            SELECT t.id as drop_id, d.keep_id
            FROM journal_tags t
            JOIN duplicates d ON lower(t.name) = d.lname AND t.id != d.keep_id
        )
        UPDATE journal_tag_assignments jta
        SET tag_id = tm.keep_id
        FROM to_merge tm
        WHERE jta.tag_id = tm.drop_id;
    """)

    # 3. Update any journal_tags that have a dropped tag as parent
    op.execute("""
        WITH duplicates AS (
            SELECT lower(name) as lname, min(id::text)::uuid as keep_id
            FROM journal_tags
            GROUP BY lower(name)
            HAVING count(*) > 1
        ),
        to_merge AS (
            SELECT t.id as drop_id, d.keep_id
            FROM journal_tags t
            JOIN duplicates d ON lower(t.name) = d.lname AND t.id != d.keep_id
        )
        UPDATE journal_tags t
        SET parent_id = tm.keep_id
        FROM to_merge tm
        WHERE t.parent_id = tm.drop_id;
    """)

    # 4. Delete the duplicate journal_tags
    op.execute("""
        WITH duplicates AS (
            SELECT lower(name) as lname, min(id::text)::uuid as keep_id
            FROM journal_tags
            GROUP BY lower(name)
            HAVING count(*) > 1
        )
        DELETE FROM journal_tags t
        USING duplicates d
        WHERE lower(t.name) = d.lname AND t.id != d.keep_id;
    """)

    # --- Update Constraints ---

    # tags table
    op.execute("ALTER TABLE tags DROP CONSTRAINT IF EXISTS tags_name_key")
    op.execute("DROP INDEX IF EXISTS idx_tags_name")
    op.execute("CREATE UNIQUE INDEX uq_tags_name_lower ON tags (LOWER(name))")

    # journal_tags table
    op.execute(
        "ALTER TABLE journal_tags DROP CONSTRAINT IF EXISTS uq_journal_tags_name"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_journal_tags_name_lower ON journal_tags (LOWER(name))"
    )


def downgrade() -> None:
    # journal_tags table
    op.execute("DROP INDEX IF EXISTS uq_journal_tags_name_lower")
    op.create_unique_constraint("uq_journal_tags_name", "journal_tags", ["name"])

    # tags table
    op.execute("DROP INDEX IF EXISTS uq_tags_name_lower")
    op.create_unique_constraint("tags_name_key", "tags", ["name"])
    op.create_index("idx_tags_name", "tags", ["name"])
