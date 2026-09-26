"""
Unit tests for MCP shared converters.

Tests the converter utilities for transforming domain entities to AI-friendly formats.
"""

from datetime import datetime

from core_shared.models.contacts.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactSummary,
    MethodType,
    SummaryStatus,
    Tag,
)
from core_shared.models.contacts.value_objects import TagName

from app.mcp.domains.contacts.schemas import ContactResponse, ContactSearchResult
from app.mcp.shared.converters import (
    ContactConverter,
    SearchResponseConverter,
    SearchResultProcessor,
)


class TestContactConverter:
    """Test ContactConverter functionality."""

    def test_to_contact_response_basic(self):
        """Test basic contact conversion to response format."""
        # Create a basic contact
        contact = Contact(
            id=123,
            first_name="John",
            last_name="Doe",
        )

        # Convert to response
        response = ContactConverter.to_contact_response(contact)

        # Verify response structure
        assert isinstance(response, ContactResponse)
        assert response.id == "123"
        assert response.name == "John Doe"
        assert response.email is None
        assert response.phone is None
        assert response.tags == []
        assert "John Doe is a contact" in response.summary

    def test_to_contact_response_with_additional_context(self):
        """Test contact conversion with additional context."""
        contact = Contact(
            id=456,
            first_name="Jane",
            last_name="Smith",
        )

        # Convert with additional context
        response = ContactConverter.to_contact_response(
            contact, additional_context="Recently updated"
        )

        # Verify additional context is included
        assert "Recently updated" in response.summary

    def test_to_contact_response_with_tags(self):
        """Test contact conversion with tags."""
        contact = Contact(
            id=789,
            first_name="Bob",
            last_name="Wilson",
        )

        # Add tags
        tag1 = Tag(name=TagName("friend"))
        tag2 = Tag(name=TagName("work"))
        contact.tags = [tag1, tag2]

        # Convert to response
        response = ContactConverter.to_contact_response(contact)

        # Verify tags are included
        assert "friend" in response.tags
        assert "work" in response.tags
        assert "tagged as: friend, work" in response.summary

    def test_to_search_result_basic(self):
        """Test basic search hit conversion to search result format."""
        search_hit = {
            "id": 123,
            "first_name": "John",
            "last_name": "Doe",
            "full_name": "John Doe",
            "email": "john@example.com",
            "phone": "+1234567890",
            "tags": ["friend"],
            "_formatted": {"first_name": "<mark>John</mark>"},
        }

        # Convert to search result
        result = ContactConverter.to_search_result(search_hit)

        # Verify result structure
        assert isinstance(result, ContactSearchResult)
        assert result.id == "123"
        assert result.name == "John Doe"
        assert result.email == "john@example.com"
        assert result.phone == "+1234567890"
        assert "friend" in result.tags
        assert result.highlighted == {"first_name": "<mark>John</mark>"}
        assert "John Doe is a contact" in result.summary

    def test_to_search_result_with_additional_context(self):
        """Test search hit conversion with additional context."""
        search_hit = {
            "id": 456,
            "first_name": "Jane",
            "last_name": "Smith",
            "full_name": "Jane Smith",
        }

        # Convert with additional context
        result = ContactConverter.to_search_result(
            search_hit, additional_context="High relevance"
        )

        # Verify additional context is included
        assert "High relevance" in result.summary


class TestSearchResponseConverter:
    """Test SearchResponseConverter functionality."""

    def test_build_search_summary_basic(self):
        """Test basic search summary building."""
        summary = SearchResponseConverter.build_search_summary(
            query="john",
            total_hits=5,
            processing_time_ms=25,
        )

        # Verify summary content
        assert "Found 5 contacts matching 'john'" in summary
        assert "Search completed in 25ms" in summary

    def test_build_search_summary_with_filters(self):
        """Test search summary with filters."""
        summary = SearchResponseConverter.build_search_summary(
            query="john",
            total_hits=3,
            processing_time_ms=15,
            filters={"tags": ["friend", "work"]},
        )

        # Verify filter information is included
        assert "Filtered by tags: friend, work" in summary

    def test_build_search_summary_with_available_tags(self):
        """Test search summary with available tags."""
        available_tags = ["friend", "work", "family", "colleague"]

        summary = SearchResponseConverter.build_search_summary(
            query="john",
            total_hits=2,
            processing_time_ms=10,
            available_tags=available_tags,
        )

        # Verify available tags are included
        assert (
            "Available tags for filtering: friend, work, family, colleague" in summary
        )

    def test_build_global_search_summary(self):
        """Test global search summary building."""
        summary = SearchResponseConverter.build_global_search_summary(
            query="project",
            total_hits=8,
            processing_time_ms=30,
            searched_entity_types=["contact", "journal"],
            available_entity_types=["contact", "journal", "calendar"],
        )

        # Verify global search summary content
        assert "Found 8 results matching 'project' across 2 entity types" in summary
        assert "Search completed in 30ms" in summary
        assert "Searched entity types: contact, journal" in summary
        assert "Available entity types: contact, journal, calendar" in summary


class TestSearchResultProcessor:
    """Test SearchResultProcessor functionality."""

    def test_process_contact_search_hits(self):
        """Test processing contact search hits."""
        hits = [
            {
                "id": 123,
                "first_name": "John",
                "last_name": "Doe",
                "full_name": "John Doe",
                "email": "john@example.com",
                "tags": ["friend"],
            },
            {
                "id": 456,
                "first_name": "Jane",
                "last_name": "Smith",
                "full_name": "Jane Smith",
                "phone": "+1234567890",
                "tags": ["work"],
            },
        ]

        # Process hits
        results = SearchResultProcessor.process_contact_search_hits(hits)

        # Verify results
        assert len(results) == 2
        assert all(isinstance(result, ContactSearchResult) for result in results)
        assert results[0].name == "John Doe"
        assert results[1].name == "Jane Smith"

    def test_process_contact_search_hits_with_context(self):
        """Test processing contact search hits with additional context."""
        hits = [
            {
                "id": 789,
                "first_name": "Bob",
                "last_name": "Wilson",
                "full_name": "Bob Wilson",
            }
        ]

        # Process with additional context
        results = SearchResultProcessor.process_contact_search_hits(
            hits, additional_context="Recent activity"
        )

        # Verify context is included
        assert len(results) == 1
        assert "Recent activity" in results[0].summary

    def test_process_global_search_hits(self):
        """Test processing global search hits."""
        hits = [
            {
                "id": 123,
                "first_name": "John",
                "last_name": "Doe",
                "full_name": "John Doe",
                "email": "john@example.com",
                "tags": ["friend"],
            }
        ]

        # Process global search hits
        results = SearchResultProcessor.process_global_search_hits(hits)

        # Verify results include entity context
        assert len(results) == 1
        assert isinstance(results[0], ContactSearchResult)
        assert "Found in contact database" in results[0].summary

    def test_process_global_search_hits_with_context(self):
        """Test processing global search hits with additional context."""
        hits = [
            {
                "id": 456,
                "first_name": "Jane",
                "last_name": "Smith",
                "full_name": "Jane Smith",
            }
        ]

        # Process with additional context
        results = SearchResultProcessor.process_global_search_hits(
            hits, additional_context="Cross-entity search"
        )

        # Verify both contexts are included
        assert len(results) == 1
        assert "Cross-entity search" in results[0].summary
        assert "Found in contact database" in results[0].summary


class TestContactConverterAISummary:
    """Test ContactConverter AI interaction summary integration."""

    def test_contact_with_generated_summary_populates_ai_fields(self):
        """When a contact has a GENERATED summary, interaction_summary and follow_up_suggestions are populated."""
        contact = Contact(
            id=100,
            first_name="Alice",
            last_name="Smith",
            summary=ContactSummary(
                contact_id=100,
                summary_text="Alice is a close colleague who we meet weekly.",
                follow_up_suggestions=[
                    "Schedule coffee catch-up",
                    "Share project update",
                ],
                status=SummaryStatus.GENERATED,
                generated_at=datetime(2026, 4, 20, 10, 0, 0),
            ),
        )

        response = ContactConverter.to_contact_response(contact)

        assert (
            response.interaction_summary
            == "Alice is a close colleague who we meet weekly."
        )
        assert response.follow_up_suggestions == [
            "Schedule coffee catch-up",
            "Share project update",
        ]
        # The metadata summary should also include the AI interaction text
        assert "Alice is a close colleague who we meet weekly." in response.summary

    def test_contact_with_pending_summary_has_empty_ai_fields(self):
        """When a contact has a PENDING summary, AI fields are None/empty."""
        contact = Contact(
            id=101,
            first_name="Bob",
            last_name="Jones",
            summary=ContactSummary(
                contact_id=101,
                summary_text=None,
                follow_up_suggestions=[],
                status=SummaryStatus.PENDING,
            ),
        )

        response = ContactConverter.to_contact_response(contact)

        assert response.interaction_summary is None
        assert response.follow_up_suggestions == []

    def test_contact_without_summary_entity_has_empty_ai_fields(self):
        """When a contact has no summary entity at all, AI fields default to None/empty."""
        contact = Contact(
            id=102,
            first_name="Charlie",
            last_name="Brown",
            summary=None,
        )

        response = ContactConverter.to_contact_response(contact)

        assert response.interaction_summary is None
        assert response.follow_up_suggestions == []

    def test_contact_with_user_override_uses_override_text(self):
        """When the summary has a user override, interaction_summary uses override text."""
        contact = Contact(
            id=103,
            first_name="Diana",
            last_name="Prince",
            summary=ContactSummary(
                contact_id=103,
                summary_text="AI generated text that should be ignored",
                user_override_text="Manually written summary about Diana",
                is_user_override=True,
                follow_up_suggestions=["Send follow-up email"],
                status=SummaryStatus.GENERATED,
                generated_at=datetime(2026, 4, 15, 8, 0, 0),
            ),
        )

        response = ContactConverter.to_contact_response(contact)

        assert response.interaction_summary == "Manually written summary about Diana"
        assert response.follow_up_suggestions == ["Send follow-up email"]
        # Override text should appear in metadata summary
        assert "Manually written summary about Diana" in response.summary


class TestContactFields:
    """Every email, phone and address, by id; archived ones only on request."""

    @staticmethod
    def _contact() -> Contact:
        return Contact(
            id=1,
            first_name="Ada",
            methods=[
                ContactMethod(
                    id=10,
                    method_type=MethodType.EMAIL,
                    value="ada@example.com",
                    contact_id=1,
                    label="work",
                    is_primary=True,
                ),
                ContactMethod(
                    id=11,
                    method_type=MethodType.PHONE,
                    value="+44 20 7946 0000",
                    contact_id=1,
                    is_archived=True,
                ),
            ],
            addresses=[
                ContactAddress(
                    id=20,
                    street_line_1="1 Childhood Rd",
                    locality="Bathurst",
                    country_code="AU",
                    contact_id=1,
                    is_archived=True,
                )
            ],
        )

    def test_archived_values_are_left_out_by_default(self) -> None:
        response = ContactConverter.to_contact_response(self._contact())

        assert [f.model_dump() for f in response.contact_fields] == [
            {
                "id": 10,
                "kind": "email",
                "value": "ada@example.com",
                "label": "work",
                "is_primary": True,
                "is_archived": False,
            }
        ]
        assert "+44 20 7946 0000" not in response.summary

    def test_include_archived_adds_them(self) -> None:
        response = ContactConverter.to_contact_response(
            self._contact(), include_archived=True
        )

        assert [
            (f.id, f.kind, f.value, f.is_archived) for f in response.contact_fields
        ] == [
            (10, "email", "ada@example.com", False),
            (11, "phone", "+44 20 7946 0000", True),
            (20, "address", "1 Childhood Rd, Bathurst, AU", True),
        ]
