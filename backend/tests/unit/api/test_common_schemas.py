"""
Tests for common API schemas and utilities.

Tests the shared utilities used across API controllers.
"""

from unittest.mock import Mock

from app.api.common.schemas import (
    create_pagination_links,
    get_request_base_url,
)


class TestGetRequestBaseUrl:
    """Test base URL extraction from requests."""

    def test_simple_url(self):
        """Test extracting base URL from simple request."""
        mock_request = Mock()
        mock_request.base_url = "https://api.example.com/"

        result = get_request_base_url(mock_request)

        assert result == "https://api.example.com"

    def test_url_without_trailing_slash(self):
        """Test extracting base URL that doesn't have trailing slash."""
        mock_request = Mock()
        mock_request.base_url = "https://api.example.com"

        result = get_request_base_url(mock_request)

        assert result == "https://api.example.com"

    def test_url_with_port(self):
        """Test extracting base URL with port number."""
        mock_request = Mock()
        mock_request.base_url = "http://localhost:8000/"

        result = get_request_base_url(mock_request)

        assert result == "http://localhost:8000"


class TestCreatePaginationLinksWithParams:
    """Test pagination links creation with additional parameters."""

    def test_basic_pagination_links(self):
        """Test creating basic pagination links without additional params."""
        links = create_pagination_links(
            base_url="https://api.example.com/search", page=2, limit=10, total_count=50
        )

        assert links.self == "https://api.example.com/search?page=2&limit=10"
        assert links.first == "https://api.example.com/search?page=1&limit=10"
        assert links.last == "https://api.example.com/search?page=5&limit=10"
        assert links.prev == "https://api.example.com/search?page=1&limit=10"
        assert links.next == "https://api.example.com/search?page=3&limit=10"

    def test_pagination_links_with_string_params(self):
        """Test creating pagination links with string parameters."""
        additional_params: dict[str, str | list[str]] = {"q": "john", "sort": "name"}

        links = create_pagination_links(
            base_url="https://api.example.com/search",
            page=1,
            limit=20,
            total_count=100,
            additional_params=additional_params,
        )

        expected_params = "&q=john&sort=name"
        assert (
            links.self
            == f"https://api.example.com/search?page=1&limit=20{expected_params}"
        )
        assert (
            links.first
            == f"https://api.example.com/search?page=1&limit=20{expected_params}"
        )
        assert (
            links.last
            == f"https://api.example.com/search?page=5&limit=20{expected_params}"
        )
        assert links.prev is None  # First page
        assert (
            links.next
            == f"https://api.example.com/search?page=2&limit=20{expected_params}"
        )

    def test_pagination_links_with_list_params(self):
        """Test creating pagination links with list parameters."""
        additional_params: dict[str, str | list[str]] = {
            "tags": ["friend", "work"],
            "q": "jane",
        }

        links = create_pagination_links(
            base_url="https://api.example.com/search",
            page=3,
            limit=10,
            total_count=50,
            additional_params=additional_params,
        )

        # Should include all list items and string params
        assert links.self is not None
        assert "q=jane" in links.self
        assert "tags=friend" in links.self
        assert "tags=work" in links.self
        assert links.self.startswith("https://api.example.com/search?page=3&limit=10")

    def test_pagination_links_mixed_params(self):
        """Test creating pagination links with mixed string and list parameters."""
        additional_params: dict[str, str | list[str]] = {
            "q": "search term",
            "entity_types": ["contact", "task"],
            "sort": "created_at",
        }

        links = create_pagination_links(
            base_url="https://api.example.com/search",
            page=2,
            limit=25,
            total_count=75,
            additional_params=additional_params,
        )

        # Check that all parameters are included
        assert links.self is not None
        assert "q=search+term" in links.self
        assert "entity_types=contact" in links.self
        assert "entity_types=task" in links.self
        assert "sort=created_at" in links.self

    def test_pagination_links_empty_params(self):
        """Test creating pagination links with empty additional params."""
        links = create_pagination_links(
            base_url="https://api.example.com/search",
            page=1,
            limit=10,
            total_count=5,
            additional_params={},
        )

        assert links.self == "https://api.example.com/search?page=1&limit=10"
        assert links.next is None  # Only one page
        assert links.prev is None  # First page

    def test_pagination_links_none_params(self):
        """Test creating pagination links with None additional params."""
        links = create_pagination_links(
            base_url="https://api.example.com/search",
            page=1,
            limit=10,
            total_count=5,
            additional_params=None,
        )

        assert links.self == "https://api.example.com/search?page=1&limit=10"

    def test_pagination_links_last_page(self):
        """Test pagination links on the last page."""
        links = create_pagination_links(
            base_url="https://api.example.com/search",
            page=5,
            limit=10,
            total_count=50,
            additional_params={"q": "test"},
        )

        assert links.next is None  # Last page
        assert links.prev == "https://api.example.com/search?page=4&limit=10&q=test"

    def test_pagination_links_zero_total(self):
        """Test pagination links with zero total count."""
        links = create_pagination_links(
            base_url="https://api.example.com/search", page=1, limit=10, total_count=0
        )

        assert links.self == "https://api.example.com/search?page=1&limit=10"
        assert links.first is None
        assert links.last is None
        assert links.prev is None
        assert links.next is None
