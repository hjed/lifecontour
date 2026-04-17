"""
Integration tests for important date synchronization.

Tests the full inbound and outbound sync flows with real PostgreSQL
database, verifying that:
1. Inbound: Google birthday/anniversary events are transformed and persisted
2. Outbound: Local dates are correctly pushed to Google format
3. Local-only types are filtered during outbound push
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import (
    _load_full_contact,
    _transform_contact_to_google_person,
    push_local_contacts_to_google,
)


@pytest.mark.asyncio
class TestOutboundDateSync:
    """Test that outbound push includes correct date data from DB."""

    async def test_load_full_contact_includes_important_dates(
        self, db_session: AsyncSession
    ) -> None:
        """_load_full_contact loads important dates from the database."""
        # Create a contact
        contact_result = await db_session.execute(
            text(
                """
                INSERT INTO contacts (first_name, last_name)
                VALUES ('DateSync', 'Test')
                RETURNING id
                """
            )
        )
        contact_id = contact_result.scalar_one()

        # Add a birthday
        await db_session.execute(
            text(
                """
                INSERT INTO contact_important_dates
                    (contact_id, date_type, precision, year, month, day)
                VALUES (:cid, 'birthday', 'full', 1990, 5, 20)
                """
            ),
            {"cid": contact_id},
        )

        # Add marriage anniversary
        await db_session.execute(
            text(
                """
                INSERT INTO contact_important_dates
                    (contact_id, date_type, precision, year, month, day)
                VALUES (:cid, 'marriage_anniversary', 'day_month', NULL, 6, 20)
                """
            ),
            {"cid": contact_id},
        )

        await db_session.flush()

        full_data = await _load_full_contact(db_session, contact_id)

        assert "important_dates" in full_data
        assert len(full_data["important_dates"]) == 2

        birthday = full_data["important_dates"][0]
        assert birthday["date_type"] == "birthday"
        assert birthday["precision"] == "full"
        assert birthday["year"] == 1990
        assert birthday["month"] == 5
        assert birthday["day"] == 20

        anniversary = full_data["important_dates"][1]
        assert anniversary["date_type"] == "marriage_anniversary"
        assert anniversary["precision"] == "day_month"

    async def test_push_contact_with_birthday_to_google(
        self, db_session: AsyncSession
    ) -> None:
        """Full push workflow includes birthday in Google person data."""
        # Setup auth
        test_email = "date-push@example.com"
        test_user = "date-push-1"
        fernet_key = Fernet.generate_key()
        fernet = Fernet(fernet_key)
        now = datetime.now(UTC)

        await db_session.execute(
            text(
                """
                INSERT INTO user_google_auth (
                    user_id, google_account_email,
                    encrypted_access_token, encrypted_refresh_token,
                    expires_at, created_at, updated_at
                ) VALUES (
                    :user_id, :email, :token, :refresh,
                    :expiry, :now, :now
                )
                ON CONFLICT (user_id, google_account_email) DO NOTHING
                """
            ),
            {
                "user_id": test_user,
                "email": test_email,
                "token": fernet.encrypt(b"access_token"),
                "refresh": fernet.encrypt(b"refresh_token"),
                "expiry": now + timedelta(hours=1),
                "now": now,
            },
        )

        # Create contact with birthday
        contact_result = await db_session.execute(
            text(
                """
                INSERT INTO contacts (first_name, last_name)
                VALUES ('Birthday', 'Push')
                RETURNING id
                """
            )
        )
        contact_id = contact_result.scalar_one()

        await db_session.execute(
            text(
                """
                INSERT INTO contact_important_dates
                    (contact_id, date_type, precision, year, month, day)
                VALUES (:cid, 'birthday', 'full', 1990, 5, 20)
                """
            ),
            {"cid": contact_id},
        )

        await db_session.commit()

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        ctx = {
            "session_factory": mock_session_factory,
            "redis": None,
            "job_id": "date_push_test",
        }

        captured_person_data: dict[str, Any] = {}

        with (
            patch(
                "worker.settings.encryption_key.get_secret_value",
                return_value=fernet_key.decode(),
            ),
            patch("google_client.build") as mock_build,
        ):
            mock_service = MagicMock()

            # Capture the person data sent to createContact
            def capture_create(body: Any = None, **kwargs: Any) -> MagicMock:
                captured_person_data.update(body or {})
                mock_req = MagicMock()
                mock_req.execute = MagicMock(
                    return_value={
                        "resourceName": "people/c_date_push",
                        "etag": "etag_date",
                    }
                )
                return mock_req

            mock_people = MagicMock()
            mock_people.createContact.side_effect = capture_create
            mock_service.people.return_value = mock_people

            # Mock contact groups
            mock_groups = MagicMock()
            mock_list_req = MagicMock()
            mock_list_req.execute = MagicMock(return_value={"contactGroups": []})
            mock_groups.list.return_value = mock_list_req
            mock_service.contactGroups.return_value = mock_groups

            mock_build.return_value = mock_service

            result = await push_local_contacts_to_google(
                ctx=ctx,
                google_account_email=test_email,
                user_id=test_user,
            )

        assert result["status"] == "success"
        assert result["pushed_count"] == 1

        # Verify birthday was included in the Google person data
        assert "birthdays" in captured_person_data
        assert len(captured_person_data["birthdays"]) == 1
        assert captured_person_data["birthdays"][0] == {
            "date": {"year": 1990, "month": 5, "day": 20}
        }

    async def test_push_filters_local_only_date_types(
        self, db_session: AsyncSession
    ) -> None:
        """Outbound push excludes local-only date types from Google payload."""
        # Create contact with local-only date types
        contact_result = await db_session.execute(
            text(
                """
                INSERT INTO contacts (first_name, last_name)
                VALUES ('LocalOnly', 'Dates')
                RETURNING id
                """
            )
        )
        contact_id = contact_result.scalar_one()

        # Add work anniversary (local-only)
        await db_session.execute(
            text(
                """
                INSERT INTO contact_important_dates
                    (contact_id, date_type, precision, year, month, day)
                VALUES (:cid, 'work_anniversary', 'full', 2020, 1, 1)
                """
            ),
            {"cid": contact_id},
        )

        # Add first_met (local-only)
        await db_session.execute(
            text(
                """
                INSERT INTO contact_important_dates
                    (contact_id, date_type, precision, year, month, day)
                VALUES (:cid, 'first_met', 'full', 2019, 7, 4)
                """
            ),
            {"cid": contact_id},
        )

        await db_session.flush()

        full_data = await _load_full_contact(db_session, contact_id)
        contact_dict: dict[str, Any] = {
            "first_name": "LocalOnly",
            "last_name": "Dates",
            "methods": full_data["methods"],
            "addresses": full_data["addresses"],
            "notes": full_data["notes"],
            "important_dates": full_data["important_dates"],
        }

        person_data = _transform_contact_to_google_person(contact_dict)

        # Local-only types should result in empty lists in Google output so removals propagate
        assert person_data.get("birthdays") == []
        assert person_data.get("events") == []
