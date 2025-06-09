"""
Contact domain MCP schemas.

AI-friendly data formats for contact information that provide
structured, contextual data for AI analysis and decision making.
"""

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
                "summary": "John is a software engineer and close friend who works at TechCorp. We collaborate on side projects and meet regularly for coffee.",
            }
        }
