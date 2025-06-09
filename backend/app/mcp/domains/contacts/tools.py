"""
Contact domain MCP tools.

Provides AI access to contact management functionality through MCP tools.
Each tool is designed to return AI-friendly, contextual information.
"""

import json
from typing import Annotated

import structlog
from fastmcp import FastMCP
from pydantic import Field

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.mcp.domains.contacts.schemas import ContactResponse
from app.mcp.shared.dependencies import get_contact_service

logger = structlog.get_logger()


def register_contact_tools(mcp: FastMCP[None]) -> None:
    """
    Register contact-related MCP tools with the FastMCP server.

    Args:
        mcp: The FastMCP server instance to register tools with
    """

    @mcp.tool
    async def get_contact(
        contact_id: Annotated[
            int, Field(description="The unique identifier of the contact")
        ],
    ) -> str:
        """
        Get contact details by ID for AI analysis.

        Retrieves comprehensive contact information including name, contact methods,
        tags, and a contextual summary. The response is formatted for AI consumption
        to help with relationship management and decision making.

        Args:
            contact_id: The unique identifier of the contact

        Returns:
            JSON string containing AI-friendly contact information including:
            - Basic contact details (name, email, phone)
            - Associated tags for categorization
            - Contextual summary for AI understanding

        Raises:
            ContactNotFoundError: If the contact with the given ID does not exist
        """
        try:
            logger.info("MCP: Getting contact details", contact_id=contact_id)

            # Get contact service
            contact_service = await get_contact_service()

            # Fetch contact data
            contact = await contact_service.get_contact_by_id(contact_id)

            if contact is None:
                raise ContactNotFoundError(contact_id)

            # Extract primary email and phone using Contact entity methods
            primary_email = contact.get_primary_email()
            primary_phone = contact.get_primary_phone()

            # Extract tag names
            tag_names = [str(tag.name) for tag in contact.tags]

            # Create AI-friendly summary
            full_name = contact.get_full_name()
            summary_parts = [f"{full_name} is a contact"]

            if tag_names:
                tag_list = ", ".join(tag_names)
                summary_parts.append(f"tagged as: {tag_list}")

            # Include notes if available
            if contact.notes:
                # Get the most recent note
                latest_note = contact.notes[0] if contact.notes else None
                if latest_note:
                    summary_parts.append(f"Notes: {latest_note.content}")

            if primary_email:
                summary_parts.append(f"Primary email: {primary_email}")

            if primary_phone:
                summary_parts.append(f"Primary phone: {primary_phone}")

            summary = ". ".join(summary_parts) + "."

            # Create response
            response = ContactResponse(
                id=str(contact.id),
                name=full_name,
                email=primary_email,
                phone=primary_phone,
                tags=tag_names,
                summary=summary,
            )

            logger.info(
                "MCP: Contact retrieved successfully",
                contact_id=contact_id,
                contact_name=contact.get_full_name(),
            )

            return json.dumps(response.model_dump(), indent=2)

        except ContactNotFoundError:
            logger.warning("MCP: Contact not found", contact_id=contact_id)
            error_response = {
                "error": "Contact not found",
                "contact_id": contact_id,
                "message": f"No contact exists with ID: {contact_id}",
            }
            return json.dumps(error_response, indent=2)

        except Exception as e:
            logger.error(
                "MCP: Error retrieving contact", contact_id=contact_id, error=str(e)
            )
            error_response = {
                "error": "Internal error",
                "contact_id": contact_id,
                "message": "An error occurred while retrieving the contact",
            }
            return json.dumps(error_response, indent=2)
