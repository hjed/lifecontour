"""SQL access to ``contact_import_issues``: what imports left out, for review."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import String, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.import_issues import ContactImportIssue

_SELECT = """
    SELECT i.id, i.contact_id, i.integration_source, i.kind, i.reason,
           i.payload, i.status, i.created_at,
           TRIM(c.first_name || ' ' || COALESCE(c.last_name, '')) AS contact_name
    FROM contact_import_issues i
    JOIN contacts c ON c.id = i.contact_id AND c.user_id = i.user_id
"""


class SqlContactImportIssueRepository:
    """Records, lists and dismisses ``user_id``'s import issues."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def replace(
        self,
        *,
        user_id: str,
        contact_id: int,
        integration_source: str,
        external_id: str,
        kind: str,
        issues: Sequence[tuple[str, dict[str, Any]]],
    ) -> None:
        """Make the contact's ``kind`` issues from the source exactly ``issues``.

        ``issues`` are ``(reason, payload)`` pairs, as the latest applied import
        reports them. One no longer reported is gone (fixed at the source); one
        already recorded keeps its status, so a dismissed one stays dismissed.
        """
        payloads = [json.dumps(payload, sort_keys=True) for _, payload in issues]
        await self.connection.execute(
            text(
                """
                DELETE FROM contact_import_issues
                WHERE user_id = :user_id AND contact_id = :contact_id
                  AND integration_source = :integration_source AND kind = :kind
                  AND NOT (payload_hash = ANY(
                      SELECT md5(CAST(p AS JSONB)::text) FROM unnest(:payloads) AS p
                  ))
                """
            ).bindparams(bindparam("payloads", type_=ARRAY(String))),
            {
                "user_id": user_id,
                "contact_id": contact_id,
                "integration_source": integration_source,
                "kind": kind,
                "payloads": payloads,
            },
        )
        for (reason, _), payload in zip(issues, payloads, strict=True):
            await self.connection.execute(
                text(
                    """
                    INSERT INTO contact_import_issues (
                        user_id, contact_id, integration_source, external_id, kind,
                        reason, payload, payload_hash
                    ) VALUES (
                        :user_id, :contact_id, :integration_source, :external_id,
                        :kind, :reason, CAST(:payload AS JSONB),
                        md5(CAST(:payload AS JSONB)::text)
                    )
                    ON CONFLICT ON CONSTRAINT uq_contact_import_issues_payload
                    DO UPDATE SET external_id = EXCLUDED.external_id,
                                  updated_at = now()
                    """
                ),
                {
                    "user_id": user_id,
                    "contact_id": contact_id,
                    "integration_source": integration_source,
                    "external_id": external_id,
                    "kind": kind,
                    "reason": reason,
                    "payload": payload,
                },
            )

    async def list_pending(
        self, user_id: str, *, contact_id: int | None = None
    ) -> list[ContactImportIssue]:
        """The user's pending issues, newest first, optionally for one contact."""
        result = await self.connection.execute(
            text(
                _SELECT
                + """
                WHERE i.user_id = :user_id AND i.status = 'pending'
                  AND (CAST(:contact_id AS INTEGER) IS NULL
                       OR i.contact_id = :contact_id)
                ORDER BY i.created_at DESC, i.id DESC
                """
            ),
            {"user_id": user_id, "contact_id": contact_id},
        )
        return [_to_issue(row) for row in result.fetchall()]

    async def dismiss(self, user_id: str, issue_id: int) -> bool:
        """Dismiss one of the user's issues; whether they hold it."""
        result = await self.connection.execute(
            text(
                """
                UPDATE contact_import_issues
                SET status = 'dismissed', updated_at = now()
                WHERE id = :issue_id AND user_id = :user_id
                RETURNING id
                """
            ),
            {"user_id": user_id, "issue_id": issue_id},
        )
        return result.fetchone() is not None


def _to_issue(row: Any) -> ContactImportIssue:
    return ContactImportIssue(
        id=int(row.id),
        contact_id=int(row.contact_id),
        contact_name=str(row.contact_name),
        integration_source=str(row.integration_source),
        kind=str(row.kind),
        reason=str(row.reason),
        payload=dict(row.payload),
        status=str(row.status),
        created_at=row.created_at,
    )
