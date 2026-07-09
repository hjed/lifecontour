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
    ImportantDate,
    MethodType,
    Tag,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.contacts.value_objects import TagName

from api_models import GoogleBirthday, GoogleDate, GooglePerson, GooglePersonEvent
from group_translator import GoogleGroupNameTranslator

logger = structlog.get_logger()


class GoogleContactTransformer:
    """
    Transforms Google People API contacts to internal Contact entities.

    Handles the conversion of Google's contact format to our domain model,
    including proper mapping of names, contact methods, addresses, and metadata.
    """

    def __init__(self, translator: GoogleGroupNameTranslator | None = None) -> None:
        """
        Initialize the transformer.

        Args:
            translator: Translator for Google Contact Groups. If None, an empty one is used.
        """
        self.translator = translator or GoogleGroupNameTranslator(
            reserved_group_ids=[], group_mapping={}
        )

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

        is_favourite = False
        for membership in google_person.memberships:
            group_info = getattr(membership, "contact_group_membership", None)
            if group_info:
                group_id = self._extract_group_id(group_info)
                if group_id == "starred":
                    is_favourite = True
                    break

        contact = Contact(
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            nick_name=nick_name,
            is_favourite=is_favourite,
        )

        # Methods: Google is authoritative — always provide a list (even if empty)
        methods: list[ContactMethod] = []
        methods.extend(self._transform_email_addresses(google_person.email_addresses))
        methods.extend(self._transform_phone_numbers(google_person.phone_numbers))
        contact.methods = methods

        # Addresses, notes, tags: use None when Google provides no data
        # so that locally-managed data is preserved on sync updates.
        transformed_addresses = self._transform_addresses(google_person.addresses)
        contact.addresses = transformed_addresses or None

        transformed_notes = self._transform_biographies(google_person.biographies)
        contact.notes = transformed_notes or None

        # Tags: Google memberships are explicitly requested in personFields,
        # so an empty list IS authoritative (contact has no group memberships).
        contact.tags = self._transform_memberships_to_tags(google_person.memberships)

        company, job_title = self._extract_organization_info(
            google_person.organizations
        )
        contact.company = company
        contact.job_title = job_title

        # Important dates: birthdays and events
        contact.important_dates = self._transform_dates(
            google_person.birthdays, google_person.events
        )

        logger.debug(
            "Successfully transformed Google person to contact",
            resource_name=google_person.resource_name,
            contact_methods_count=len(contact.methods),
            addresses_count=len(contact.addresses or []),
            notes_count=len(contact.notes or []),
            tags_count=len(contact.tags or []),
            important_dates_count=len(contact.important_dates or []),
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
        return self._transform_contact_methods(email_addresses, MethodType.EMAIL)

    def _transform_phone_numbers(self, phone_numbers: list[Any]) -> list[ContactMethod]:
        """Transform Google phone numbers to ContactMethod entities."""
        return self._transform_contact_methods(
            phone_numbers,
            MethodType.PHONE,
            preferred_value_attr="canonical_form",
        )

    def _transform_contact_methods(
        self,
        contact_values: list[Any],
        method_type: MethodType,
        preferred_value_attr: str | None = None,
    ) -> list[ContactMethod]:
        """Transform Google contact methods into validated ContactMethod entities."""
        contact_methods = []

        for contact_value in contact_values:
            value = self._extract_contact_method_value(
                contact_value, preferred_value_attr=preferred_value_attr
            )
            if not value:
                continue

            contact_method = self._create_contact_method(
                method_type=method_type,
                value=value,
                label=self._extract_field_label(contact_value),
                is_primary=self._is_primary_field(contact_value),
            )
            if contact_method:
                contact_methods.append(contact_method)

        return contact_methods

    def _extract_contact_method_value(
        self,
        contact_value: Any,
        preferred_value_attr: str | None = None,
    ) -> str | None:
        """Extract the most useful method value from a Google field."""
        if preferred_value_attr:
            preferred_value = getattr(contact_value, preferred_value_attr, None)
            if isinstance(preferred_value, str) and preferred_value:
                return preferred_value

        value = getattr(contact_value, "value", None)
        if isinstance(value, str) and value:
            return value

        return None

    def _extract_field_label(self, field_value: Any) -> str | None:
        """Extract a display label from a Google field value."""
        formatted_type = getattr(field_value, "formatted_type", None)
        if isinstance(formatted_type, str) and formatted_type:
            return formatted_type

        fallback_type = getattr(field_value, "type", None)
        if isinstance(fallback_type, str) and fallback_type:
            return fallback_type

        return None

    def _is_primary_field(self, field_value: Any) -> bool:
        """Return whether a Google field is marked as primary."""
        metadata = getattr(field_value, "metadata", None)
        return bool(getattr(metadata, "primary", False))

    def _transform_addresses(self, addresses: list[Any]) -> list[ContactAddress]:
        """Transform Google addresses to ContactAddress entities."""
        contact_addresses = []

        for address in addresses:
            is_primary = self._is_primary_field(address)

            street_line_1 = getattr(address, "street_address", None)
            if not street_line_1 and hasattr(address, "formatted_value"):
                street_line_1 = address.formatted_value

            if street_line_1 and getattr(address, "country_code", None):
                contact_address = self._create_contact_address(
                    street_line_1=street_line_1,
                    country_code=address.country_code,
                    street_line_2=getattr(address, "extended_address", None),
                    locality=getattr(address, "city", None),
                    region=getattr(address, "region", None),
                    postal_code=getattr(address, "postal_code", None),
                    is_primary=is_primary,
                )
                if contact_address:
                    contact_addresses.append(contact_address)

        return contact_addresses

    def _transform_biographies(self, biographies: list[Any]) -> list[ContactNote]:
        """Transform Google biographies to ContactNote entities."""
        notes = []

        for bio in biographies:
            if not hasattr(bio, "value") or not bio.value:
                continue

            note = self._create_contact_note(bio.value)
            if note:
                notes.append(note)

        return notes

    def _create_contact_method(
        self,
        method_type: MethodType,
        value: str,
        label: str | None,
        is_primary: bool,
    ) -> ContactMethod | None:
        """Create a validated contact method, skipping invalid values."""
        try:
            return ContactMethod(
                method_type=method_type,
                value=value,
                label=label,
                is_primary=is_primary,
                contact_id=0,
            )
        except ValueError as exc:
            logger.warning(
                "Skipping invalid Google contact method",
                method_type=method_type.value,
                value=value,
                label=label,
                error=str(exc),
            )
            return None

    def _create_contact_address(
        self,
        street_line_1: str,
        country_code: str,
        street_line_2: str | None,
        locality: str | None,
        region: str | None,
        postal_code: str | None,
        is_primary: bool,
    ) -> ContactAddress | None:
        """Create a validated contact address, skipping invalid values."""
        try:
            return ContactAddress(
                street_line_1=street_line_1,
                country_code=country_code,
                street_line_2=street_line_2,
                locality=locality,
                region=region,
                postal_code=postal_code,
                is_primary=is_primary,
                contact_id=0,
            )
        except ValueError as exc:
            logger.warning(
                "Skipping invalid Google contact address",
                street_line_1=street_line_1,
                country_code=country_code,
                error=str(exc),
            )
            return None

    def _create_contact_note(self, content: str) -> ContactNote | None:
        """Create a validated contact note, skipping invalid values."""
        try:
            return ContactNote(content=content, contact_id=0)
        except ValueError as exc:
            logger.warning(
                "Skipping invalid Google contact note",
                error=str(exc),
            )
            return None

    def _transform_memberships_to_tags(self, memberships: list[Any]) -> list[Tag]:
        """Transform Google contact group memberships to Tag entities.

        Handles hierarchical group names containing '/' by splitting them
        into parent→child tag chains. Deduplicates tags by name,
        case-insensitively — tag identity in the backend is case-insensitive,
        so case-variant group names must collapse to a single tag.
        """
        tags: list[Tag] = []
        seen_names: set[str] = set()

        for membership in memberships:
            chain = self._create_tags_from_membership(membership)
            for tag in chain:
                folded_name = tag.name.value.casefold()
                if folded_name not in seen_names:
                    seen_names.add(folded_name)
                    tags.append(tag)

        return tags

    def _create_tags_from_membership(self, membership: Any) -> list[Tag]:
        """Create tag(s) from a Google membership, splitting '/' into parent→child chains."""
        group_info = getattr(membership, "contact_group_membership", None)
        if not group_info:
            return []

        group_id = self._extract_group_id(group_info)
        resource_name = self._extract_resource_name(group_info)

        if self.translator.is_reserved(group_id):
            return []

        fallback_name = self._extract_membership_group_name(membership)
        translated_name = self.translator.translate(
            resource_name, fallback_name=fallback_name
        )

        if not translated_name:
            return []

        name_str = str(translated_name)

        # Split on '/' for hierarchy
        segments = [s.strip() for s in name_str.split("/") if s.strip()]
        if not segments:
            return []

        tags: list[Tag] = []
        for segment in segments:
            try:
                sanitized = self._sanitize_tag_name(segment)
                if sanitized:
                    tag = Tag(name=TagName(sanitized))
                    # For child tags in a hierarchy, set _parent_name so
                    # serialization can carry the relationship info.
                    if tags:
                        tag._parent_name = tags[-1].name.value  # type: ignore[attr-defined]
                    tags.append(tag)
            except ValueError:
                logger.debug(
                    "Skipping invalid segment in hierarchical group name",
                    segment=segment,
                    full_name=name_str,
                )

        return tags

    def _create_tag_from_membership(self, membership: Any) -> Tag | None:
        """Create a single tag from a Google membership (legacy, flat names only)."""
        tags = self._create_tags_from_membership(membership)
        return tags[0] if tags else None

    def _extract_group_id(self, group_info: Any) -> str | None:
        """Extract the contact group ID."""
        if isinstance(group_info, dict):
            return group_info.get("contactGroupId")
        return getattr(group_info, "contact_group_id", None)

    def _extract_resource_name(self, group_info: Any) -> str | None:
        """Extract the contact group resource name."""
        if isinstance(group_info, dict):
            return group_info.get("contactGroupResourceName")
        return getattr(group_info, "contact_group_resource_name", None)

    def _extract_membership_group_name(self, membership: Any) -> str | None:
        """Extract the contact group name or identifier from a membership."""
        group_info = getattr(membership, "contact_group_membership", None)
        if not group_info:
            return None

        if isinstance(group_info, dict):
            return self._extract_group_name_from_dict(group_info)

        return self._extract_group_name_from_object(group_info)

    def _extract_group_name_from_dict(self, group_info: dict[str, Any]) -> str | None:
        """Extract the preferred group name from a dict-style membership."""
        return (
            group_info.get("contactGroupId")
            or group_info.get("contactGroupResourceName")
            or group_info.get("name")
        )

    def _extract_group_name_from_object(self, group_info: Any) -> str | None:
        """Extract the preferred group name from an object-style membership."""
        return getattr(group_info, "contact_group_id", None) or getattr(
            group_info, "contact_group_resource_name", None
        )

    def _sanitize_tag_name(self, name: str) -> str | None:
        """
        Sanitize a string to make it valid for TagName.

        TagName only allows alphanumeric, hyphens, underscores, and ampersands.
        The '/' character should be split before this method is called.
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

    # ── Important date helpers ──────────────────────────────────────────

    # Mapping of Google event types to internal date types.
    # Only supported types are included; all others are silently skipped.
    _GOOGLE_EVENT_TYPE_MAP: dict[str, ImportantDateType] = {
        "anniversary": ImportantDateType.MARRIAGE_ANNIVERSARY,
    }

    def _transform_dates(
        self,
        birthdays: list[GoogleBirthday],
        events: list[GooglePersonEvent],
    ) -> list[ImportantDate] | None:
        """Transform Google birthdays and events into ImportantDate entities.

        Returns None when both lists are empty (Google provided no date
        data), which signals the sync layer to preserve local-only dates.
        Returns a (possibly empty) list when at least one source had data.
        """
        birthday_dates = self._transform_birthdays(birthdays)
        event_dates = self._transform_events(events)
        transformed_dates = birthday_dates + event_dates

        # Only trigger downstream replacement when Google produced at least
        # one supported, valid important date. Unsupported event types or
        # invalid date payloads should preserve existing local-only dates.
        if not transformed_dates:
            return None

        return transformed_dates

    def _transform_birthdays(
        self, birthdays: list[GoogleBirthday]
    ) -> list[ImportantDate]:
        """Transform Google birthday entries to ImportantDate entities."""
        results: list[ImportantDate] = []
        for birthday in birthdays:
            if birthday.date is None:
                continue
            important_date = self._google_date_to_important_date(
                birthday.date, ImportantDateType.BIRTHDAY
            )
            if important_date:
                results.append(important_date)
        return results

    def _transform_events(self, events: list[GooglePersonEvent]) -> list[ImportantDate]:
        """Transform Google event entries to ImportantDate entities.

        Only events whose type maps to a supported ImportantDateType are
        included.  Unknown types are silently skipped.
        """
        results: list[ImportantDate] = []
        for event in events:
            if event.date is None or event.type is None:
                continue

            date_type = self._GOOGLE_EVENT_TYPE_MAP.get(event.type.lower())
            if date_type is None:
                logger.debug(
                    "Skipping unsupported Google event type",
                    event_type=event.type,
                )
                continue

            important_date = self._google_date_to_important_date(event.date, date_type)
            if important_date:
                results.append(important_date)
        return results

    @staticmethod
    def _google_date_to_important_date(
        date: GoogleDate, date_type: ImportantDateType
    ) -> ImportantDate | None:
        """Convert a Google Date to an ImportantDate with inferred precision.

        Google uses 0 (or None) to mean "not set" for date components.
        Precision mapping:
        - year>0, month>0, day>0 → FULL
        - year==0/None, month>0, day>0 → DAY_MONTH
        - year>0, month==0/None, day==0/None → YEAR
        - All zero/None → skip (return None)
        """
        year = date.year if date.year and date.year > 0 else None
        month = date.month if date.month and date.month > 0 else None
        day = date.day if date.day and date.day > 0 else None

        if year and month and day:
            precision = DatePrecision.FULL
        elif month and day:
            precision = DatePrecision.DAY_MONTH
            year = None  # ensure no year for this precision
        elif year:
            precision = DatePrecision.YEAR
            month = None
            day = None
        else:
            # No usable components
            return None

        return ImportantDate(
            contact_id=0,
            date_type=date_type,
            precision=precision,
            year=year,
            month=month,
            day=day,
        )
