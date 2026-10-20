import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def test_get_user_settings_reports_an_unset_timezone_as_null(
    authenticated_client: AsyncClient,
):
    """GET answers ``null`` when the user has never configured a timezone.

    Substituting the ``UTC`` default here would make "never set" look exactly
    like "deliberately chose UTC", and the frontend cannot tell them apart: it
    would anchor every unconfigured user's date writes at UTC midnight rather
    than falling back to the browser's zone, which is a calendar day out for
    anyone ahead of UTC (issue #1401). The default still applies everywhere the
    backend resolves a zone for itself.
    """
    response = await authenticated_client.get("/api/user-settings")

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["type"] == "user_settings"
    assert data["data"]["attributes"]["timezone"] is None
    assert data["data"]["attributes"]["default_country"] is None


async def test_patch_and_get_user_settings(authenticated_client: AsyncClient):
    """PATCH saves the timezone and GET returns the saved value."""
    put_response = await authenticated_client.patch(
        "/api/user-settings",
        json={"timezone": "Australia/Sydney"},
    )

    assert put_response.status_code == 200
    put_data = put_response.json()
    assert put_data["data"]["attributes"]["timezone"] == "Australia/Sydney"

    get_response = await authenticated_client.get("/api/user-settings")
    assert get_response.status_code == 200
    assert get_response.json()["data"]["attributes"]["timezone"] == "Australia/Sydney"


async def test_patch_user_settings_upserts(authenticated_client: AsyncClient):
    """A second PATCH updates the existing timezone."""
    await authenticated_client.patch(
        "/api/user-settings", json={"timezone": "Australia/Sydney"}
    )
    second = await authenticated_client.patch(
        "/api/user-settings", json={"timezone": "America/New_York"}
    )

    assert second.status_code == 200
    assert second.json()["data"]["attributes"]["timezone"] == "America/New_York"

    get_response = await authenticated_client.get("/api/user-settings")
    assert get_response.json()["data"]["attributes"]["timezone"] == "America/New_York"


async def test_patch_user_settings_rejects_invalid_timezone(
    authenticated_client: AsyncClient,
):
    """PATCH rejects an unknown timezone name with a validation error."""
    response = await authenticated_client.patch(
        "/api/user-settings", json={"timezone": "Not/A_Zone"}
    )

    assert response.status_code == 400
    assert "errors" in response.json()


async def test_patch_default_country_alone_leaves_the_timezone_unset(
    authenticated_client: AsyncClient,
) -> None:
    """Saving only a country must not record a timezone choice (issue #1401)."""
    response = await authenticated_client.patch(
        "/api/user-settings", json={"default_country": "NZ"}
    )

    assert response.status_code == 200
    attributes = response.json()["data"]["attributes"]
    assert attributes == {"timezone": None, "default_country": "NZ"}

    get_response = await authenticated_client.get("/api/user-settings")
    assert get_response.json()["data"]["attributes"] == {
        "timezone": None,
        "default_country": "NZ",
    }


async def test_patch_timezone_keeps_the_default_country(
    authenticated_client: AsyncClient,
) -> None:
    """A field the PATCH omits is left as it is."""
    await authenticated_client.patch(
        "/api/user-settings", json={"default_country": "AU"}
    )
    response = await authenticated_client.patch(
        "/api/user-settings", json={"timezone": "Australia/Perth"}
    )

    assert response.json()["data"]["attributes"] == {
        "timezone": "Australia/Perth",
        "default_country": "AU",
    }


async def test_patch_null_default_country_clears_it(
    authenticated_client: AsyncClient,
) -> None:
    """An explicit null clears the default country, keeping the timezone."""
    await authenticated_client.patch(
        "/api/user-settings",
        json={"timezone": "Europe/London", "default_country": "GB"},
    )
    response = await authenticated_client.patch(
        "/api/user-settings", json={"default_country": None}
    )

    assert response.json()["data"]["attributes"] == {
        "timezone": "Europe/London",
        "default_country": None,
    }


@pytest.mark.parametrize(
    "body",
    [
        {"default_country": "AUS"},
        {"default_country": "au"},
        {"default_country": ""},
        {"default_country": "ZZ"},
        {"timezone": None},
    ],
    ids=["alpha-3", "lowercase", "empty", "not-a-country", "null-timezone"],
)
async def test_patch_user_settings_rejects_invalid_values(
    authenticated_client: AsyncClient, body: dict[str, str | None]
) -> None:
    """Country must be ISO 3166-1 alpha-2; the timezone cannot be cleared."""
    response = await authenticated_client.patch("/api/user-settings", json=body)

    assert response.status_code == 400
    assert "errors" in response.json()
