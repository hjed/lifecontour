"""Seed contact import issues - addresses an import skipped for review."""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.contact_seeding import TEST_USER_ID


async def seed_skipped_address(
    conn: AsyncConnection,
    contact_id: int,
    *,
    street: str = "10 Downing St",
    user_id: str = TEST_USER_ID,
    status: str = "pending",
) -> int:
    """Record that an import skipped ``street`` (an unrecognised AU region)."""
    payload = {
        "street_line_1": street,
        "street_line_2": None,
        "locality": "London",
        "region": "London",
        "postal_code": None,
        "country_code": "AU",
    }
    result = await conn.execute(
        text(
            """
            INSERT INTO contact_import_issues (
                user_id, contact_id, integration_source, external_id, kind,
                reason, payload, payload_hash, status
            ) VALUES (
                :user_id, :contact_id, 'google', 'people/cSeed', 'skipped_address',
                'unrecognised_region', CAST(:payload AS JSONB), md5(CAST(:payload AS JSONB)::text), :status
            )
            RETURNING id
            """
        ),
        {
            "user_id": user_id,
            "contact_id": contact_id,
            "payload": json.dumps(payload, sort_keys=True),
            "status": status,
        },
    )
    return int(result.scalar_one())
