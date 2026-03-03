"""
Data transformer for converting Google Contacts to internal Contact format.

Handles the mapping between Google People API response structures and our
internal Contact domain entities.
"""

import re
from typing import Any

import structlog
from core_shared.models.contacts.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    MethodType,
    Tag,
)
from core_shared.models.contacts.value_objects import TagName

from api_models import GooglePerson

logger = structlog.get_logger()


class GoogleContactTransformer:
    """
    Transforms Google People API contacts to internal Contact entities.

    Handles the conversion of Google's contact format to our domain model,
    including proper mapping of names, contact methods, addresses, and metadata.
    """

    def transform_person(self, google_person: GooglePerson) -> Contact:
        """
        Transform a Google Person to our internal Contact entity.

        Args:
            google_person: Google People API person object

        Returns:
            Contact entity with transformed data
        """
        logger.debug(
            "Transforming Google person to contact",
            resource_name=google_person.resource_name,
            has_names=len(google_person.names) > 0,
            has_emails=len(google_person.email_addresses) > 0,
            has_phones=len(google_person.phone_numbers) > 0,
        )

        first_name, last_name, middle_name, nick_name = self._extract_names(
            google_person.names
        )

        if not first_name:
            first_name = "Unknown"

        contact = Contact(
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            nick_name=nick_name,
            is_favourite=False,
        )

        contact.methods.extend(
            self._transform_email_addresses(google_person.email_addresses)
        )
        contact.methods.extend(
            self._transform_phone_numbers(google_person.phone_numbers)
        )

        contact.addresses.extend(self._transform_addresses(google_person.addresses))
        contact.notes.extend(self._transform_biographies(google_person.biographies))
        contact.tags.extend(
            self._transform_memberships_to_tags(google_person.memberships)
        )

        company, job_title = self._extract_organization_info(
            google_person.organizations
        )
        contact.company = company
        contact.job_title = job_title

        logger.debug(
            "Successfully transformed Google person to contact",
            resource_name=google_person.resource_name,
            contact_methods_count=len(contact.methods),
            addresses_count=len(contact.addresses),
            notes_count=len(contact.notes),
            tags_count=len(contact.tags),
            company=contact.company,
            job_title=contact.job_title,
        )

        return contact

    def _extract_names(
        self, names: list[Any]
    ) -> tuple[str | None, str | None, str | None, str | None]:
        """Extract name components from Google names array."""
        if not names:
            return None, None, None, None

        primary_name = None
        for name in names:
            if hasattr(name, "metadata") and name.metadata.primary:
                primary_name = name
                break

        if not primary_name:
            primary_name = names[0]

        return (
            getattr(primary_name, "given_name", None),
            getattr(primary_name, "family_name", None),
            getattr(primary_name, "middle_name", None),
            None,
        )

    def _transform_email_addresses(
        self, email_addresses: list[Any]
    ) -> list[ContactMethod]:
        """Transform Google email addresses to ContactMethod entities."""
        contact_methods = []

        for email in email_addresses:
            if not hasattr(email, "value") or not email.value:
                continue

            is_primary = hasattr(email, "metadata") and email.metadata.primary

            label = None
            if hasattr(email, "formatted_type") and email.formatted_type:
                label = email.formatted_type
            elif hasattr(email, "type") and email.type:
                label = email.type

            contact_methods.append(
                ContactMethod(
                    method_type=MethodType.EMAIL,
                    value=email.value,
                    label=label,
                    is_primary=is_primary,
                    contact_id=0,
                )
            )

        return contact_methods

    def _transform_phone_numbers(self, phone_numbers: list[Any]) -> list[ContactMethod]:
        """Transform Google phone numbers to ContactMethod entities."""
        contact_methods = []

        for phone in phone_numbers:
            if not hasattr(phone, "value") or not phone.value:
                continue

            is_primary = hasattr(phone, "metadata") and phone.metadata.primary

            label = None
            if hasattr(phone, "formatted_type") and phone.formatted_type:
                label = phone.formatted_type
            elif hasattr(phone, "type") and phone.type:
                label = phone.type

            phone_value = phone.value
            if hasattr(phone, "canonical_form") and phone.canonical_form:
                phone_value = phone.canonical_form

            contact_methods.append(
                ContactMethod(
                    method_type=MethodType.PHONE,
                    value=phone_value,
                    label=label,
                    is_primary=is_primary,
                    contact_id=0,
                )
            )

        return contact_methods

    def _transform_addresses(self, addresses: list[Any]) -> list[ContactAddress]:
        """Transform Google addresses to ContactAddress entities."""
        contact_addresses = []

        for address in addresses:
            is_primary = hasattr(address, "metadata") and address.metadata.primary

            street_line_1 = getattr(address, "street_address", None)
            if not street_line_1 and hasattr(address, "formatted_value"):
                street_line_1 = address.formatted_value

            if street_line_1 and getattr(address, "country_code", None):
                contact_addresses.append(
                    ContactAddress(
                        street_line_1=street_line_1,
                        country_code=address.country_code,
                        street_line_2=getattr(address, "extended_address", None),
                        locality=getattr(address, "city", None),
                        region=getattr(address, "region", None),
                        postal_code=getattr(address, "postal_code", None),
                        is_primary=is_primary,
                        contact_id=0,
                    )
                )

        return contact_addresses

    def _transform_biographies(self, biographies: list[Any]) -> list[ContactNote]:
        """Transform Google biographies to ContactNote entities."""
        notes = []

        for bio in biographies:
            if not hasattr(bio, "value") or not bio.value:
                continue

            notes.append(
                ContactNote(
                    content=bio.value,
                    contact_id=0,
                )
            )

        return notes

    def _transform_memberships_to_tags(self, memberships: list[Any]) -> list[Tag]:
        """Transform Google contact group memberships to Tag entities."""
        tags = []

        for membership in memberships:
            if (
                hasattr(membership, "contact_group_membership")
                and membership.contact_group_membership
            ):
                group_info = membership.contact_group_membership

                group_name = None
                if isinstance(group_info, dict):
                    group_name = (
                        group_info.get("contactGroupId")
                        or group_info.get("contactGroupResourceName")
                        or group_info.get("name")
                    )
                else:
                    group_name = getattr(
                        group_info, "contact_group_id", None
                    ) or getattr(group_info, "contact_group_resource_name", None)

                if group_name:
                    try:
                        sanitized_name = self._sanitize_tag_name(str(group_name))
                        if sanitized_name:
                            tags.append(Tag(name=TagName(sanitized_name)))
                    except ValueError:
                        logger.debug(
                            "Skipping invalid contact group name for tag",
                            group_name=group_name,
                        )

        return tags

    def _sanitize_tag_name(self, name: str) -> str | None:
        """
        Sanitize a string to make it valid for TagName.

        TagName only allows alphanumeric, hyphens, underscores, and ampersands.
        """
        if not name or not name.strip():
            return None

        sanitized = re.sub(r"[^a-zA-Z0-9_&-]", "-", name.strip())
        sanitized = re.sub(r"-+", "-", sanitized)
        sanitized = sanitized.strip("-")

        if not sanitized or len(sanitized) > 100:
            return None

        return sanitized

    def _extract_organization_info(
        self, organizations: list[Any]
    ) -> tuple[str | None, str | None]:
        """Extract company and job title from Google organizations."""
        if not organizations:
            return (None, None)

        selected_org = None
        for org in organizations:
            if hasattr(org, "current") and org.current is True:
                selected_org = org
                break

        if selected_org is None:
            selected_org = organizations[0]

        company = None
        if hasattr(selected_org, "name") and selected_org.name:
            company = selected_org.name.strip() if selected_org.name.strip() else None

        job_title = None
        if hasattr(selected_org, "title") and selected_org.title:
            job_title = (
                selected_org.title.strip() if selected_org.title.strip() else None
            )

        logger.debug(
            "Extracted organization info",
            company=company,
            job_title=job_title,
            total_organizations=len(organizations),
        )

        return (company, job_title)
