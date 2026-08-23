"""
MCP entity conversion utilities.

Provides utilities for converting domain entities to AI-friendly MCP response formats,
reducing duplication and ensuring consistent response structures.
"""

from typing import Any

from core_shared.etag import resource_etag
from core_shared.models.contacts.entities import Contact, ContactRelationship

from app.mcp.domains.contacts.schemas import (
    ContactRelationshipSchema,
    ContactResponse,
    ContactSearchResult,
    GlobalSearchResponse,
    ImportantDateInfo,
)
from app.mcp.domains.journals.schemas import ExternalLinkSchema


class ContactConverter:
    """Converter for Contact entities to MCP response formats."""

    @staticmethod
    def _format_work_info(job_title: str | None, company: str | None) -> str | None:
        """
        Format work information (job title and company) into a readable string.

        Args:
            job_title: Job title or position
            company: Company or organization name

        Returns:
            Formatted work information string, or None if no work info available
        """
        if job_title and company:
            return f"{job_title} at {company}"
        elif job_title:
            return job_title
        elif company:
            return f"works at {company}"
        return None

    @staticmethod
    def to_contact_response(
        contact: Contact,
        additional_context: str = "",
        external_links: list[ExternalLinkSchema] | None = None,
    ) -> ContactResponse:
        """
        Convert a Contact entity to an AI-friendly ContactResponse.

        Args:
            contact: Contact domain entity
            additional_context: Additional context to include in summary

        Returns:
            ContactResponse optimized for AI consumption
        """
        # Extract basic contact information
        full_name = contact.get_full_name()
        primary_email = contact.get_primary_email()
        primary_phone = contact.get_primary_phone()
        tag_names = [str(tag.name) for tag in (contact.tags or [])]

        important_dates = []
        for d in contact.important_dates or []:
            important_dates.append(
                ImportantDateInfo(
                    date_type=d.date_type.value,
                    precision=d.precision.value,
                    year=d.year,
                    month=d.month,
                    day=d.day,
                    custom_type_name=d.custom_date_type_name,
                )
            )

        relationships_list = []
        for rel in contact.relationships or []:
            if rel.to_user:
                rel_type = str(rel.relationship_type.value).replace("_", " ").title()
                relationships_list.append(f"{rel_type} of the User")
            elif rel.from_contact_id == contact.id:
                # the other person is to_contact_id
                rel_type = str(rel.relationship_type.value).replace("_", " ").title()
                other_name = rel.to_contact_name or "Unknown contact"
                relationships_list.append(f"{rel_type} of {other_name}")
            else:
                # the other person is from_contact_id, so the contact is the 'to_contact_id'
                # we need to invert the relationship
                inv_type = (
                    rel.relationship_type.get_inverse_type()
                    .value.replace("_", " ")
                    .title()
                )
                other_name = rel.from_contact_name or "Unknown contact"
                relationships_list.append(f"{inv_type} of {other_name}")

        # Build AI-friendly summary
        summary = ContactConverter._build_contact_summary(
            full_name=full_name,
            tags=tag_names,
            email=primary_email,
            phone=primary_phone,
            company=contact.company,
            job_title=contact.job_title,
            notes=contact.notes,
            important_dates=important_dates,
            relationships=relationships_list,
            additional_context=additional_context,
        )

        # Extract AI interaction summary from the contact summary entity
        interaction_summary: str | None = None
        ai_follow_up_suggestions: list[str] = []

        if contact.summary is not None:
            from core_shared.models.contacts.entities import SummaryStatus

            cs = contact.summary
            # Mirror the frontend display text logic:
            # User override text always takes precedence.
            # AI summary_text only used when status is GENERATED.
            if cs.is_user_override and cs.user_override_text:
                interaction_summary = cs.user_override_text
            elif cs.status == SummaryStatus.GENERATED and cs.summary_text:
                interaction_summary = cs.summary_text

            if cs.status == SummaryStatus.GENERATED:
                ai_follow_up_suggestions = cs.follow_up_suggestions or []

            # Append AI interaction summary to the metadata summary for full context
            if interaction_summary:
                summary = f"{summary}\n\nAI Interaction Summary: {interaction_summary}"

        return ContactResponse(
            id=str(contact.id),
            name=full_name,
            email=primary_email,
            phone=primary_phone,
            company=contact.company,
            job_title=contact.job_title,
            photo_url=contact.photo_url,
            tags=tag_names,
            relationships=relationships_list,
            is_favourite=contact.is_favourite,
            important_dates=important_dates,
            summary=summary,
            interaction_summary=interaction_summary,
            follow_up_suggestions=ai_follow_up_suggestions,
            external_links=external_links or [],
            version=resource_etag("contacts", contact.id, contact.updated_at)
            if contact.id is not None
            else None,
        )

    @staticmethod
    def to_search_result(
        search_hit: dict[str, Any], additional_context: str = ""
    ) -> ContactSearchResult:
        """
        Convert a search hit to an AI-friendly ContactSearchResult.

        Args:
            search_hit: Search result from MeiliSearch
            additional_context: Additional context to include in summary

        Returns:
            ContactSearchResult optimized for AI consumption
        """
        # Extract search hit information
        contact_id = str(search_hit.get("id", ""))
        first_name = search_hit.get("first_name", "")
        last_name = search_hit.get("last_name", "")
        full_name = search_hit.get("full_name", f"{first_name} {last_name}".strip())
        email = search_hit.get("email")
        phone = search_hit.get("phone")
        company = search_hit.get("company")
        job_title = search_hit.get("job_title")
        tags = search_hit.get("tags", [])
        relationships = search_hit.get("relationships", [])
        highlighted = search_hit.get("_formatted", {})

        # Build AI-friendly summary with search context
        summary_parts = [f"{full_name} is a contact"]
        if tags:
            tag_list = ", ".join(tags)
            summary_parts.append(f"tagged as: {tag_list}")

        if relationships:
            rel_list = ", ".join(relationships)
            summary_parts.append(f"relationships: {rel_list}")

        # Add work information
        work_info = ContactConverter._format_work_info(job_title, company)
        if work_info:
            summary_parts.append(work_info)

        if email:
            summary_parts.append(f"Email: {email}")
        if phone:
            summary_parts.append(f"Phone: {phone}")

        # Add search relevance context
        if highlighted:
            summary_parts.append("Found through search highlighting")

        if additional_context:
            summary_parts.append(additional_context)

        summary = ". ".join(summary_parts) + "."

        return ContactSearchResult(
            id=contact_id,
            name=full_name,
            email=email,
            phone=phone,
            company=company,
            job_title=job_title,
            tags=tags,
            relationships=relationships,
            highlighted=highlighted,
            summary=summary,
        )

    @staticmethod
    def _build_contact_summary(
        full_name: str,
        tags: list[str],
        email: str | None = None,
        phone: str | None = None,
        company: str | None = None,
        job_title: str | None = None,
        notes: list[Any] | None = None,
        important_dates: list[ImportantDateInfo] | None = None,
        relationships: list[str] | None = None,
        additional_context: str = "",
    ) -> str:
        """
        Build an AI-friendly summary for a contact.

        Args:
            full_name: Contact's full name
            tags: List of tag names
            email: Primary email address
            phone: Primary phone number
            company: Company or organization name
            job_title: Job title or position
            notes: List of contact notes
            important_dates: List of important dates
            relationships: List of relationships
            additional_context: Additional context to include

        Returns:
            AI-friendly summary string
        """
        summary_parts = [f"{full_name} is a contact"]

        if tags:
            tag_list = ", ".join(tags)
            summary_parts.append(f"tagged as: {tag_list}")

        if relationships:
            rel_list = ", ".join(relationships)
            summary_parts.append(f"relationships: {rel_list}")

        # Add work information
        work_info = ContactConverter._format_work_info(job_title, company)
        if work_info:
            summary_parts.append(work_info)

        # Include notes if available
        if notes:
            # Get the most recent note
            latest_note = notes[0] if notes else None
            if latest_note and hasattr(latest_note, "content"):
                summary_parts.append(f"Notes: {latest_note.content}")

        if email:
            summary_parts.append(f"Primary email: {email}")

        if phone:
            summary_parts.append(f"Primary phone: {phone}")

        if important_dates:
            seen_date_contexts = set()
            date_contexts = []
            for d in important_dates:
                date_label = None
                if d.date_type == "birthday":
                    date_label = "Birthday"
                elif d.date_type == "first_met":
                    date_label = "First Met"
                elif d.date_type == "custom":
                    custom_type_name = (d.custom_type_name or "").strip()
                    if custom_type_name:
                        date_label = custom_type_name
                else:
                    date_label = d.date_type.replace("_", " ").title()

                if date_label and date_label not in seen_date_contexts:
                    seen_date_contexts.add(date_label)
                    date_contexts.append(date_label)

            if date_contexts:
                summary_parts.append(f"Has dates for: {', '.join(date_contexts)}")

        if additional_context:
            summary_parts.append(additional_context)

        return ". ".join(summary_parts) + "."


class ContactRelationshipConverter:
    """Converter for ContactRelationship entities to MCP response formats."""

    @staticmethod
    def to_relationship_response(
        relationship: ContactRelationship,
        main_contact_id: int,
    ) -> ContactRelationshipSchema:
        """
        Convert a ContactRelationship entity to an AI-friendly ContactRelationshipSchema.
        """
        if relationship.to_user:
            # User-targeted relationship
            other_id = None
            other_name_str = relationship.to_contact_name or "You"
            rel_type = relationship.relationship_type.value
            summary = f"This contact is a {rel_type} of the user."
        elif relationship.from_contact_id == main_contact_id:
            other_id = relationship.to_contact_id
            other_name_str = relationship.to_contact_name or str(other_id)
            rel_type = relationship.relationship_type.value
            summary = f"This contact is a {rel_type} of {other_name_str}."
        else:
            other_id = relationship.from_contact_id
            # In inverse perspective, we might not have from_contact_name cached.
            other_name_str = str(other_id)
            rel_type = relationship.relationship_type.get_inverse_type().value
            summary = f"This contact is a {rel_type} of {other_name_str}."

        return ContactRelationshipSchema(
            id=relationship.id,  # type: ignore[arg-type]
            other_contact_id=other_id,
            other_contact_name=other_name_str,
            relationship_type=rel_type,
            to_user=relationship.to_user,
            summary=summary,
        )


class SearchResponseConverter:
    """Converter for search responses to AI-friendly formats."""

    @staticmethod
    def build_search_summary(
        query: str,
        total_hits: int,
        processing_time_ms: int,
        available_tags: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        additional_context: str = "",
    ) -> str:
        """
        Build an AI-friendly search summary.

        Args:
            query: Original search query
            total_hits: Total number of matching results
            processing_time_ms: Search processing time
            available_tags: Available tags for filtering
            filters: Applied filters
            additional_context: Additional context

        Returns:
            AI-friendly search summary
        """
        summary_parts = [
            f"Found {total_hits} contacts matching '{query}'",
            f"Search completed in {processing_time_ms}ms",
        ]

        if filters and "tags" in filters:
            filter_tags = filters["tags"]
            summary_parts.append(f"Filtered by tags: {', '.join(filter_tags)}")

        if available_tags:
            # Show first 10 tags to avoid overwhelming the summary
            tag_preview = ", ".join(available_tags[:10])
            if len(available_tags) > 10:
                tag_preview += f" (and {len(available_tags) - 10} more)"
            summary_parts.append(f"Available tags for filtering: {tag_preview}")

        if additional_context:
            summary_parts.append(additional_context)

        return ". ".join(summary_parts) + "."

    @staticmethod
    def build_global_search_summary(
        query: str,
        total_hits: int,
        processing_time_ms: int,
        searched_entity_types: list[str],
        available_entity_types: list[str],
        additional_context: str = "",
    ) -> str:
        """
        Build an AI-friendly global search summary.

        Args:
            query: Original search query
            total_hits: Total number of matching results
            processing_time_ms: Search processing time
            searched_entity_types: Entity types that were searched
            available_entity_types: All available entity types
            additional_context: Additional context

        Returns:
            AI-friendly global search summary
        """
        summary_parts = [
            f"Found {total_hits} results matching '{query}' across {len(searched_entity_types)} entity types",
            f"Search completed in {processing_time_ms}ms",
        ]

        if searched_entity_types:
            summary_parts.append(
                f"Searched entity types: {', '.join(searched_entity_types)}"
            )

        summary_parts.append(
            f"Available entity types: {', '.join(available_entity_types)}"
        )

        if additional_context:
            summary_parts.append(additional_context)

        return ". ".join(summary_parts) + "."

    @staticmethod
    def to_global_search_response(
        search_results: dict[str, Any], additional_context: str = ""
    ) -> GlobalSearchResponse:
        """
        Convert global search results to AI-friendly GlobalSearchResponse.

        Args:
            search_results: Global search results from SearchService
            additional_context: Additional context to include in summary

        Returns:
            GlobalSearchResponse optimized for AI consumption
        """
        # Extract search metadata
        query = search_results.get("query", "")
        total_hits = search_results.get("estimated_total_hits", 0)
        processing_time_ms = search_results.get("processing_time_ms", 0)
        searched_entity_types = search_results.get("searched_entity_types", ["contact"])
        available_entity_types = search_results.get(
            "available_entity_types", ["contact"]
        )

        # Process search hits using shared processor
        hits = search_results.get("hits", [])
        search_result_objects = SearchResultProcessor.process_global_search_hits(
            hits, additional_context
        )

        # Build AI-friendly summary
        summary = SearchResponseConverter.build_global_search_summary(
            query=query,
            total_hits=total_hits,
            processing_time_ms=processing_time_ms,
            searched_entity_types=searched_entity_types,
            available_entity_types=available_entity_types,
            additional_context=additional_context,
        )

        return GlobalSearchResponse(
            results=search_result_objects,
            query=query,
            total_hits=total_hits,
            processing_time_ms=processing_time_ms,
            searched_entity_types=searched_entity_types,
            available_entity_types=available_entity_types,
            summary=summary,
        )


class SearchResultProcessor:
    """Processor for search results to reduce duplication across search tools."""

    @staticmethod
    def process_contact_search_hits(
        hits: list[dict[str, Any]], additional_context: str = ""
    ) -> list[ContactSearchResult]:
        """
        Process search hits into ContactSearchResult objects.

        Args:
            hits: List of search hits from MeiliSearch
            additional_context: Additional context to include in summaries

        Returns:
            List of ContactSearchResult objects optimized for AI consumption
        """
        search_results = []
        for hit in hits:
            search_result = ContactConverter.to_search_result(hit, additional_context)
            search_results.append(search_result)
        return search_results

    @staticmethod
    def process_global_search_hits(
        hits: list[dict[str, Any]], additional_context: str = ""
    ) -> list[ContactSearchResult]:
        """
        Process global search hits into ContactSearchResult objects.

        Args:
            hits: List of search hits from global search
            additional_context: Additional context to include in summaries

        Returns:
            List of ContactSearchResult objects with entity type context
        """
        search_results = []
        for hit in hits:
            # Add entity type context for global search
            entity_context = "Found in contact database"
            if additional_context:
                entity_context = f"{additional_context}. {entity_context}"
            else:
                entity_context = f"{entity_context}"

            search_result = ContactConverter.to_search_result(hit, entity_context)
            search_results.append(search_result)
        return search_results
