"""
Contact domain MCP schemas.

AI-friendly data formats for contact information that provide
structured, contextual data for AI analysis and decision making.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Constants for field descriptions
_COMPANY_DESC = "Company or organization name"
_JOB_TITLE_DESC = "Job title or position"


class ImportantDateInfo(BaseModel):
    """
    AI-friendly representation of an important date.
    """

    date_type: str = Field(description="Type of date (e.g., birthday, custom)")
    precision: str = Field(description="Precision of the date (full, day_month, year)")
    year: int | None = Field(default=None, description="Year of the date")
    month: int | None = Field(default=None, description="Month (1-12)")
    day: int | None = Field(default=None, description="Day (1-31)")
    custom_type_name: str | None = Field(
        default=None, description="Name for custom date type"
    )

    @model_validator(mode="after")
    def validate_precision_components(self) -> "ImportantDateInfo":
        """Validate that the given components match the precision requirements."""
        if self.precision == "full":
            if self.year is None or self.month is None or self.day is None:
                raise ValueError("Full precision requires year, month, and day")
        elif self.precision == "day_month":
            if self.month is None or self.day is None:
                raise ValueError("Day/Month precision requires month and day")
            if self.year is not None:
                raise ValueError("Day/Month precision requires year to be omitted")
        elif self.precision == "year":
            if self.year is None:
                raise ValueError("Year precision requires year")
            if self.month is not None or self.day is not None:
                raise ValueError("Year precision requires month and day to be omitted")
        else:
            raise ValueError(
                "Unsupported precision; expected one of: full, day_month, year"
            )

        # Relax custom_type_name requirement as domain model only requires custom_date_type_id
        # if self.date_type == "custom" and self.custom_type_name is None:
        #     raise ValueError("custom_type_name is required for custom date types")

        if self.month is not None and not (1 <= self.month <= 12):
            raise ValueError("Month must be between 1 and 12")
        if self.day is not None and not (1 <= self.day <= 31):
            raise ValueError("Day must be between 1 and 31")

        return self


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

    company: str | None = Field(default=None, description=_COMPANY_DESC)

    job_title: str | None = Field(default=None, description=_JOB_TITLE_DESC)

    tags: list[str] = Field(
        default_factory=list,
        description="List of tags associated with the contact (e.g., 'friend', 'work', 'family')",
    )

    is_favourite: bool = Field(
        default=False,
        description="Whether the contact is marked as a favourite for quick access",
    )

    important_dates: list[ImportantDateInfo] = Field(
        default_factory=list,
        description="List of important dates like birthdays and anniversaries associated with the contact",
    )

    summary: str = Field(
        description="AI-friendly summary of the contact including relationship context and key details"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "contact-123",
                "name": "John Doe",
                "email": "john@example.com",
                "phone": "+1234567890",
                "company": "TechCorp",
                "job_title": "Software Engineer",
                "tags": ["friend", "work"],
                "is_favourite": True,
                "important_dates": [
                    {
                        "date_type": "birthday",
                        "precision": "full",
                        "year": 1990,
                        "month": 5,
                        "day": 15,
                        "custom_type_name": None,
                    }
                ],
                "summary": "John is a software engineer and close friend who works at TechCorp. We collaborate on side projects and meet regularly for coffee.",
            }
        }
    )


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

    company: str | None = Field(default=None, description=_COMPANY_DESC)

    job_title: str | None = Field(default=None, description=_JOB_TITLE_DESC)

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

    company: str | None = Field(default=None, description=_COMPANY_DESC)

    job_title: str | None = Field(default=None, description=_JOB_TITLE_DESC)

    email: str | None = Field(default=None, description="Primary email address")

    phone: str | None = Field(default=None, description="Primary phone number")

    tags: list[str] = Field(
        default_factory=list, description="Tags to assign to the contact"
    )

    notes: str | None = Field(
        default=None, description="Initial notes about the contact"
    )

    important_dates: list[ImportantDateInfo] | None = Field(
        default=None,
        description="List of important dates to associate with the contact",
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

    company: str | None = Field(
        default=None, description=f"Updated {_COMPANY_DESC.lower()}"
    )

    job_title: str | None = Field(
        default=None, description=f"Updated {_JOB_TITLE_DESC.lower()}"
    )

    email: str | None = Field(default=None, description="Updated primary email")

    phone: str | None = Field(default=None, description="Updated primary phone")

    tags: list[str] | None = Field(
        default=None, description="Updated tags (replaces existing tags)"
    )

    notes: str | None = Field(default=None, description="Additional notes to add")

    important_dates: list[ImportantDateInfo] | None = Field(
        default=None,
        description="Updated list of important dates (replaces existing dates)",
    )


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


class ContactRelationshipSchema(BaseModel):
    """
    AI-friendly representation of a contact relationship.

    Reflects the relationship from the perspective of the main contact being queried.
    The relationship can target either another contact or the user.
    """

    id: int = Field(description="Unique identifier for the relationship")
    other_contact_id: int | None = Field(
        default=None,
        description="ID of the other contact (None when the target is the user)",
    )
    other_contact_name: str = Field(
        description="Full name of the other contact or 'You' for user-targeted relationships"
    )
    relationship_type: str = Field(
        description="Type of relationship (e.g., parent, child, friend, colleague)"
    )
    to_user: bool = Field(
        default=False,
        description="Whether this relationship targets the user",
    )
    summary: str = Field(description="AI-friendly summary of this relationship")


class ContactRelationshipListResponse(BaseModel):
    """
    Response containing a list of relationships a contact has.
    """

    relationships: list[ContactRelationshipSchema] = Field(
        description="List of relationships for the contact"
    )
    total_count: int = Field(description="Total number of relationships")
    summary: str = Field(
        description="AI-friendly summary of the contact's relationships"
    )


class AddContactRelationshipRequest(BaseModel):
    """Request format for adding a contact relationship via MCP."""

    contact_id: int = Field(description="ID of the main contact")
    target_contact_id: int = Field(description="ID of the other contact")
    relationship_type: str = Field(
        description="Type of relationship (e.g., parent, friend)"
    )


class UpdateContactRelationshipRequest(BaseModel):
    """Request format for updating an existing contact relationship via MCP."""

    contact_id: int = Field(description="ID of the main contact")
    relationship_id: int = Field(description="ID of the relationship to update")
    relationship_type: str = Field(description="New type of relationship")


class ContactActionResponse(BaseModel):
    """Generic response format for successful non-query actions."""

    status: str = Field(description="Action resolution status (e.g., 'success').")
    message: str = Field(description="Description of the completed action.")
