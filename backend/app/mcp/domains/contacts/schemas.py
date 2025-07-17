"""
Contact domain MCP schemas.

AI-friendly data formats for contact information that provide
structured, contextual data for AI analysis and decision making.
"""

from typing import Any

from pydantic import BaseModel, Field


class ContactResponse(BaseModel):
    """
    AI-friendly contact data format.

    Provides structured contact information optimized for AI consumption,
    including contextual summary information to help AI understand
    the relationship and importance of the contact.
    """

    id: str = Field(description="Unique identifier for the contact")

    name: str = Field(description="Full name of the contact")

    email: str | None = Field(
        default=None, description="Primary email address of the contact"
    )

    phone: str | None = Field(
        default=None, description="Primary phone number of the contact"
    )

    tags: list[str] = Field(
        default_factory=list,
        description="List of tags associated with the contact (e.g., 'friend', 'work', 'family')",
    )

    is_favourite: bool = Field(
        default=False,
        description="Whether the contact is marked as a favourite for quick access",
    )

    summary: str = Field(
        description="AI-friendly summary of the contact including relationship context and key details"
    )

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "id": "contact-123",
                "name": "John Doe",
                "email": "john@example.com",
                "phone": "+1234567890",
                "tags": ["friend", "work"],
                "is_favourite": True,
                "summary": "John is a software engineer and close friend who works at TechCorp. We collaborate on side projects and meet regularly for coffee.",
            }
        }


class ContactSearchResult(BaseModel):
    """
    AI-friendly contact search result format.

    Provides search results optimized for AI consumption with highlighting
    and relevance information.
    """

    id: str = Field(description="Unique identifier for the contact")

    name: str = Field(description="Full name of the contact")

    email: str | None = Field(
        default=None, description="Primary email address of the contact"
    )

    phone: str | None = Field(
        default=None, description="Primary phone number of the contact"
    )

    tags: list[str] = Field(
        default_factory=list,
        description="List of tags associated with the contact",
    )

    highlighted: dict[str, Any] | None = Field(
        default=None, description="Highlighted fields from search with <mark> tags"
    )

    summary: str = Field(
        description="AI-friendly summary of the contact with search context"
    )


class ContactSearchResponse(BaseModel):
    """
    AI-friendly contact search response format.

    Provides search results with metadata optimized for AI analysis.
    """

    results: list[ContactSearchResult] = Field(
        description="List of contact search results"
    )

    query: str = Field(description="Original search query")

    total_hits: int = Field(description="Total number of matching contacts")

    processing_time_ms: int = Field(
        description="Search processing time in milliseconds"
    )

    available_tags: list[str] = Field(
        default_factory=list, description="Available tags for filtering"
    )

    summary: str = Field(
        description="AI-friendly summary of search results and context"
    )


class ContactCreateRequest(BaseModel):
    """
    AI-friendly contact creation request format.

    Simplified format for creating contacts through MCP tools.
    """

    first_name: str = Field(description="Contact first name")

    last_name: str | None = Field(default=None, description="Contact last name")

    middle_name: str | None = Field(default=None, description="Contact middle name")

    nick_name: str | None = Field(default=None, description="Contact nickname")

    email: str | None = Field(default=None, description="Primary email address")

    phone: str | None = Field(default=None, description="Primary phone number")

    tags: list[str] = Field(
        default_factory=list, description="Tags to assign to the contact"
    )

    notes: str | None = Field(
        default=None, description="Initial notes about the contact"
    )


class ContactUpdateRequest(BaseModel):
    """
    AI-friendly contact update request format.

    Simplified format for updating contacts through MCP tools.
    """

    contact_id: int = Field(description="ID of the contact to update")

    first_name: str | None = Field(default=None, description="Updated first name")

    last_name: str | None = Field(default=None, description="Updated last name")

    middle_name: str | None = Field(default=None, description="Updated middle name")

    nick_name: str | None = Field(default=None, description="Updated nickname")

    email: str | None = Field(default=None, description="Updated primary email")

    phone: str | None = Field(default=None, description="Updated primary phone")

    tags: list[str] | None = Field(
        default=None, description="Updated tags (replaces existing tags)"
    )

    notes: str | None = Field(default=None, description="Additional notes to add")


class ContactListResponse(BaseModel):
    """
    AI-friendly contact list response format.

    Provides paginated contact lists optimized for AI consumption.
    """

    contacts: list[ContactResponse] = Field(description="List of contacts")

    total_count: int = Field(description="Total number of contacts")

    page: int = Field(description="Current page number")

    limit: int = Field(description="Number of contacts per page")

    summary: str = Field(
        description="AI-friendly summary of the contact list and context"
    )


class GlobalSearchResponse(BaseModel):
    """
    AI-friendly global search response format.

    Provides unified search results across all entity types optimized for AI analysis.
    """

    results: list[ContactSearchResult] = Field(
        description="List of search results across all entity types"
    )

    query: str = Field(description="Original search query")

    total_hits: int = Field(description="Total number of matching results")

    processing_time_ms: int = Field(
        description="Search processing time in milliseconds"
    )

    searched_entity_types: list[str] = Field(
        description="Entity types that were searched"
    )

    available_entity_types: list[str] = Field(
        description="All available entity types in the system"
    )

    summary: str = Field(
        description="AI-friendly summary of global search results and context"
    )
