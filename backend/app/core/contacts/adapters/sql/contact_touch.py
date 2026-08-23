"""Bulk marking of contacts changed by a rewrite that does not name them.

``GET /api/contacts/{id}`` returns a contact's tags, so a change to
``contact_tags`` changes what a read of the contact returns. Merging a tag into
another or deleting one rewrites those rows for arbitrary contacts and names
none of them, which the per-contact ``ContactRepository.touch`` cannot cover.

Without this a conditional write would be accepted despite a concurrent tag
change — and the MCP ``update_contact`` tool *replaces* the whole tag set under
the caller's precondition, so the change would be clobbered rather than merely
missed. The journal side has the same pair of holes and closes them the same
way; see ``journal_touch``.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def touch_contacts_holding_tag(conn: AsyncConnection, tag_id: int) -> None:
    """Mark every contact carrying a tag as changed, locking them first.

    Run this *before* the rewrite, while the assignments still name the
    contacts to touch. Doing so also takes the parent locks ahead of the child
    writes, so this cannot deadlock against a conditional update that locks the
    contact first.
    """
    await conn.execute(
        text(
            """
            UPDATE contacts SET updated_at = now()
            WHERE id IN (
                SELECT contact_id FROM contact_tags WHERE tag_id = :tag_id
            )
            """
        ),
        {"tag_id": tag_id},
    )
