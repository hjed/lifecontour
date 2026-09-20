import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from googleapiclient.errors import HttpError


@pytest.fixture
def mock_auth_service():
    """Mock Google authentication service."""
    mock_service = AsyncMock()
    mock_service.get_access_token.return_value = "mock_access_token"
    return mock_service


@pytest.fixture
def mock_google_calendar_service():
    """Mock Google Calendar API service."""
    return MagicMock()


@pytest.mark.asyncio
async def test_get_event_success(mock_auth_service, mock_google_calendar_service):
    from google_client import GoogleAPIClient

    # Setup mock
    mock_get = mock_google_calendar_service.events.return_value.get
    mock_get.return_value.execute.return_value = {
        "id": "event123",
        "summary": "Existing Event",
    }

    client = GoogleAPIClient(
        auth_service=mock_auth_service,
        google_account_email="test@example.com",
        google_client_id="client_id",
        google_client_secret="client_secret",
        user_id=1,
    )

    with patch.object(
        client, "_get_calendar_service", return_value=mock_google_calendar_service
    ):
        result = await client.get_event("event123", "primary")

        assert result["id"] == "event123"
        assert result["summary"] == "Existing Event"
        mock_get.assert_called_once_with(calendarId="primary", eventId="event123")


@pytest.mark.asyncio
async def test_create_event_success(mock_auth_service, mock_google_calendar_service):
    from google_client import GoogleAPIClient

    # Setup mock
    mock_insert = mock_google_calendar_service.events.return_value.insert
    mock_insert.return_value.execute.return_value = {
        "id": "new_event_1",
        "summary": "New Event",
    }

    client = GoogleAPIClient(
        auth_service=mock_auth_service,
        google_account_email="test@example.com",
        google_client_id="client_id",
        google_client_secret="client_secret",
        user_id=1,
    )

    with patch.object(
        client, "_get_calendar_service", return_value=mock_google_calendar_service
    ):
        event_data = {"summary": "New Event"}
        result = await client.create_event(event_data, "primary")

        assert result["id"] == "new_event_1"
        assert result["summary"] == "New Event"
        mock_insert.assert_called_once_with(calendarId="primary", body=event_data)


@pytest.mark.asyncio
async def test_update_event_success(mock_auth_service, mock_google_calendar_service):
    """Verify update_event uses patch() (partial update) to preserve unspecified fields like attendees."""
    from google_client import GoogleAPIClient

    # Setup mock — patch() is the correct method for partial updates
    mock_patch = mock_google_calendar_service.events.return_value.patch
    mock_patch.return_value.execute.return_value = {
        "id": "event123",
        "summary": "Updated Event",
    }

    client = GoogleAPIClient(
        auth_service=mock_auth_service,
        google_account_email="test@example.com",
        google_client_id="client_id",
        google_client_secret="client_secret",
        user_id=1,
    )

    with patch.object(
        client, "_get_calendar_service", return_value=mock_google_calendar_service
    ):
        event_data = {"summary": "Updated Event"}
        result = await client.update_event("event123", event_data, "primary")

        assert result["summary"] == "Updated Event"
        # Must use patch() not update() — update() is a full replacement that
        # would remove attendees/invites when they aren't in the payload
        mock_patch.assert_called_once_with(
            calendarId="primary", eventId="event123", body=event_data
        )


@pytest.mark.asyncio
async def test_delete_event_success(mock_auth_service, mock_google_calendar_service):
    from google_client import GoogleAPIClient

    # Setup mock
    mock_delete = mock_google_calendar_service.events.return_value.delete
    mock_delete.return_value.execute.return_value = ""

    client = GoogleAPIClient(
        auth_service=mock_auth_service,
        google_account_email="test@example.com",
        google_client_id="client_id",
        google_client_secret="client_secret",
        user_id=1,
    )

    with patch.object(
        client, "_get_calendar_service", return_value=mock_google_calendar_service
    ):
        await client.delete_event("event123", "primary")
        mock_delete.assert_called_once_with(calendarId="primary", eventId="event123")


# ── eventTypeRestriction classification ─────────────────────────────────

# A 400 that is *not* a type restriction: the stale-etag conflict that
# update_contact already retries. The predicate must keep the two apart.
_ETAG_CONFLICT_CONTENT = json.dumps(
    {
        "error": {
            "code": 400,
            "message": "Request etag is different from the current etag.",
            "status": "FAILED_PRECONDITION",
            "errors": [{"domain": "global", "reason": "failedPrecondition"}],
        }
    }
).encode()


def test_is_event_type_restriction_true_for_birthday_rejection(
    event_type_restriction_error,
) -> None:
    from google_client import is_event_type_restriction

    assert is_event_type_restriction(event_type_restriction_error) is True


def test_is_event_type_restriction_false_for_etag_conflict(google_http_error) -> None:
    """A 400 etag conflict is retryable; a type restriction never is."""
    from google_client import is_event_type_restriction

    assert is_event_type_restriction(
        google_http_error(400, _ETAG_CONFLICT_CONTENT)
    ) is (False)


def test_is_event_type_restriction_false_for_server_error(google_http_error) -> None:
    from google_client import is_event_type_restriction

    error = google_http_error(500, b'{"error": {"code": 500, "message": "Backend"}}')

    assert is_event_type_restriction(error) is False


def test_is_event_type_restriction_false_for_other_status(
    google_http_error, event_type_restriction_content
) -> None:
    """The status is part of the match: only a 400 carries this rejection."""
    from google_client import is_event_type_restriction

    error = google_http_error(403, event_type_restriction_content)

    assert is_event_type_restriction(error) is False


@pytest.mark.asyncio
async def test_update_event_restriction_logs_warning_and_reraises(
    mock_auth_service, mock_google_calendar_service, event_type_restriction_error
) -> None:
    """A restriction is the caller's decision, so it is re-raised — but it is a
    permanent rejection rather than a fault, so it is not logged as an error."""
    import google_client
    from google_client import GoogleAPIClient

    mock_patch = mock_google_calendar_service.events.return_value.patch
    mock_patch.return_value.execute.side_effect = event_type_restriction_error

    client = GoogleAPIClient(
        auth_service=mock_auth_service,
        google_account_email="test@example.com",
        google_client_id="client_id",
        google_client_secret="client_secret",
        user_id=1,
    )

    with (
        patch.object(
            client, "_get_calendar_service", return_value=mock_google_calendar_service
        ),
        patch.object(google_client, "logger") as mock_logger,
    ):
        with pytest.raises(HttpError):
            await client.update_event("event123", {"summary": "New"}, "primary")

    mock_logger.warning.assert_called_once()
    mock_logger.error.assert_not_called()


def _forbidden_content(*reasons: str) -> bytes:
    """A 403 body naming the given reason codes, as Google sends it."""
    errors = ", ".join(
        f'{{"domain": "global", "reason": "{reason}", "message": "Forbidden"}}'
        for reason in reasons
    )
    return f'{{"error": {{"code": 403, "errors": [{errors}]}}}}'.encode()


class TestGoogleErrorReasons:
    """Reasons are read out of the JSON error body."""

    def test_reads_the_single_reason(self, google_http_error) -> None:
        from google_client import google_error_reasons

        error = google_http_error(403, _forbidden_content("forbidden"))

        assert google_error_reasons(error) == {"forbidden"}

    def test_reads_every_reason(self, google_http_error) -> None:
        from google_client import google_error_reasons

        error = google_http_error(
            403, _forbidden_content("forbidden", "rateLimitExceeded")
        )

        assert google_error_reasons(error) == {"forbidden", "rateLimitExceeded"}

    def test_empty_for_an_unparseable_body(self, google_http_error) -> None:
        from google_client import google_error_reasons

        assert google_error_reasons(google_http_error(403, b"<html>nope")) == set()

    def test_empty_for_a_body_without_errors(self, google_http_error) -> None:
        from google_client import google_error_reasons

        error = google_http_error(403, b'{"error": {"code": 403}}')

        assert google_error_reasons(error) == set()

    def test_empty_for_an_empty_body(self, google_http_error) -> None:
        from google_client import google_error_reasons

        assert google_error_reasons(google_http_error(403, b"")) == set()


class TestIsPermissionDenied:
    """A 403 is permanent unless Google names a rate or quota limit.

    Google answers 403 both to "you may not" and to "you are going too fast".
    Retrying the first is pointless and retrying the second is required, so
    the whole distinction rests on the reason in the body.
    """

    @pytest.mark.parametrize(
        "reason",
        [
            "forbidden",
            "forbiddenForNonOrganizer",
            "requiredAccessLevel",
            "insufficientPermissions",
        ],
    )
    def test_a_refusal_is_permanent(self, google_http_error, reason: str) -> None:
        from google_client import is_permission_denied

        assert is_permission_denied(google_http_error(403, _forbidden_content(reason)))

    @pytest.mark.parametrize(
        "reason", ["rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"]
    )
    def test_a_quota_limit_is_transient(self, google_http_error, reason: str) -> None:
        from google_client import is_permission_denied

        error = google_http_error(403, _forbidden_content(reason))

        assert is_permission_denied(error) is False

    def test_an_unreadable_403_is_treated_as_permanent(self, google_http_error) -> None:
        """A 403 we cannot read is far more likely a refusal than a quota."""
        from google_client import is_permission_denied

        assert is_permission_denied(google_http_error(403, b"Forbidden"))

    def test_a_quota_reason_wins_over_a_refusal(self, google_http_error) -> None:
        """A throttled request is retryable even when a refusal rides along."""
        from google_client import is_permission_denied

        error = google_http_error(403, _forbidden_content("forbidden", "quotaExceeded"))

        assert is_permission_denied(error) is False

    @pytest.mark.parametrize("status", [400, 404, 410, 429, 500, 503])
    def test_other_statuses_are_not_permission_denied(
        self, google_http_error, status: int
    ) -> None:
        from google_client import is_permission_denied

        error = google_http_error(status, _forbidden_content("forbidden"))

        assert is_permission_denied(error) is False
