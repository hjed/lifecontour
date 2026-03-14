from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
    from google_client import GoogleAPIClient

    # Setup mock
    mock_update = mock_google_calendar_service.events.return_value.update
    mock_update.return_value.execute.return_value = {
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
        mock_update.assert_called_once_with(
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
