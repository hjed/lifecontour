"""consolidate split recurring series

Revision ID: 0122
Revises: 0121
Create Date: 2026-10-06 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0122"
down_revision: str | None = "0121"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Google's "this and following events" split marker, as the Google worker's
# ``recurrence.root_recurring_event_id`` strips it: ``_R`` plus the split
# occurrence's start as ``YYYYMMDD`` or ``YYYYMMDDTHHMMSS[Z]``, repeated for a
# split of a split.
_SPLIT_SUFFIXES = r"(_R[0-9]{8}(T[0-9]{6}Z?)?)+$"


def upgrade() -> None:
    """Fold every split of a recurrence into one series.

    Calendar sync keyed a series on the instance's ``recurring_event_id``, and a
    "this and following" edit gives the rest of a recurrence a new one, so each
    split became a series of its own. Sync now keys on the root id; this folds
    what it already created, per ``(user, calendar, root)``, into one survivor:

    1. the series an alias already resolves the root to (the user merged it);
    2. else the series keyed on the root itself;
    3. else the earliest split, which takes the root key.

    Each absorbed series' aliases follow it to the survivor, and its own key
    becomes an alias of the survivor too — as does a renamed survivor's old
    key — so a sync payload still naming a split by its own id resolves to the
    survivor rather than re-creating the split. Members move across, and the
    absorbed series are deleted.
    """
    op.execute(
        f"""
        CREATE TEMPORARY TABLE split_series_0122 AS
        SELECT id AS series_id, user_id, calendar_id, recurring_event_id,
               created_at,
               regexp_replace(recurring_event_id, '{_SPLIT_SUFFIXES}', '') AS root
        FROM journal_series
        WHERE calendar_id IS NOT NULL AND recurring_event_id IS NOT NULL
        """
    )
    # Only groups holding at least one split need anything done.
    op.execute(
        """
        DELETE FROM split_series_0122 s
        WHERE NOT EXISTS (
            SELECT 1 FROM split_series_0122 g
            WHERE g.user_id = s.user_id
              AND g.calendar_id = s.calendar_id
              AND g.root = s.root
              AND g.recurring_event_id <> g.root
        )
        """
    )
    op.execute(
        """
        CREATE TEMPORARY TABLE split_survivors_0122 AS
        SELECT g.user_id, g.calendar_id, g.root,
               COALESCE(
                   (SELECT a.series_id
                    FROM journal_series_recurrence_aliases a
                    JOIN journal_series s ON s.id = a.series_id
                    WHERE a.calendar_id = g.calendar_id
                      AND a.recurring_event_id = g.root
                      AND s.user_id = g.user_id),
                   (SELECT s.series_id
                    FROM split_series_0122 s
                    WHERE s.user_id = g.user_id
                      AND s.calendar_id = g.calendar_id
                      AND s.recurring_event_id = g.root),
                   (SELECT s.series_id
                    FROM split_series_0122 s
                    WHERE s.user_id = g.user_id
                      AND s.calendar_id = g.calendar_id
                      AND s.root = g.root
                    ORDER BY s.created_at, s.series_id
                    LIMIT 1)
               ) AS survivor_id
        FROM (SELECT DISTINCT user_id, calendar_id, root FROM split_series_0122) g
        """
    )
    op.execute(
        """
        CREATE TEMPORARY TABLE absorbed_series_0122 AS
        SELECT s.series_id, s.user_id, s.calendar_id, s.recurring_event_id,
               v.survivor_id
        FROM split_series_0122 s
        JOIN split_survivors_0122 v
          ON v.user_id = s.user_id
         AND v.calendar_id = s.calendar_id
         AND v.root = s.root
        WHERE s.series_id <> v.survivor_id
        """
    )

    # Aliases follow their series; then each absorbed key becomes one.
    op.execute(
        """
        UPDATE journal_series_recurrence_aliases a
        SET series_id = x.survivor_id
        FROM absorbed_series_0122 x
        WHERE a.series_id = x.series_id
        """
    )
    op.execute(
        """
        INSERT INTO journal_series_recurrence_aliases
            (calendar_id, recurring_event_id, series_id, user_id)
        SELECT calendar_id, recurring_event_id, survivor_id, user_id
        FROM absorbed_series_0122
        ON CONFLICT (calendar_id, recurring_event_id)
            DO UPDATE SET series_id = EXCLUDED.series_id
        """
    )
    op.execute(
        """
        INSERT INTO journal_series_members (series_id, journal_id)
        SELECT x.survivor_id, m.journal_id
        FROM journal_series_members m
        JOIN absorbed_series_0122 x ON x.series_id = m.series_id
        ON CONFLICT (series_id, journal_id) DO NOTHING
        """
    )
    # Members and any alias still pointing here cascade.
    op.execute(
        """
        DELETE FROM journal_series
        WHERE id IN (SELECT series_id FROM absorbed_series_0122)
        """
    )

    # A survivor that is itself a split takes the root key, and keeps its old
    # key reachable as an alias. Its group's root-keyed series, if there was
    # one, was absorbed and deleted above, so the unique key is free.
    op.execute(
        f"""
        INSERT INTO journal_series_recurrence_aliases
            (calendar_id, recurring_event_id, series_id, user_id)
        SELECT s.calendar_id, s.recurring_event_id, s.id, s.user_id
        FROM journal_series s
        JOIN split_survivors_0122 v ON v.survivor_id = s.id
        WHERE s.calendar_id = v.calendar_id
          AND s.recurring_event_id <> v.root
          AND regexp_replace(s.recurring_event_id, '{_SPLIT_SUFFIXES}', '') = v.root
        ON CONFLICT (calendar_id, recurring_event_id)
            DO UPDATE SET series_id = EXCLUDED.series_id
        """
    )
    op.execute(
        f"""
        UPDATE journal_series s
        SET recurring_event_id = v.root, updated_at = now()
        FROM split_survivors_0122 v
        WHERE v.survivor_id = s.id
          AND s.calendar_id = v.calendar_id
          AND s.recurring_event_id <> v.root
          AND regexp_replace(s.recurring_event_id, '{_SPLIT_SUFFIXES}', '') = v.root
        """
    )

    op.execute("DROP TABLE absorbed_series_0122")
    op.execute("DROP TABLE split_survivors_0122")
    op.execute("DROP TABLE split_series_0122")


def downgrade() -> None:
    """Irreversible: the folded series and their memberships are gone.

    The consolidated series stay consolidated; nothing here depends on the
    schema, so downgrading past this revision is safe.
    """
