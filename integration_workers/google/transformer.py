"""
Data transformer for converting Google Contacts to internal Contact format.

Handles the mapping between Google People API response structures and our
internal Contact domain entities.
"""

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
from core_shared.models.contacts.regions import (
    is_unrecognised_region,
    normalise_region,
)
from core_shared.models.contacts.sync_scope import ContactSyncField, ContactSyncScope
from core_shared.models.contacts.value_objects import TagName
from core_shared.models.outbox_events import SkippedAddress

from address_country import resolve_address_country
from api_models import (
    GoogleAddress,
    GoogleBirthday,
    GoogleDate,
    GoogleEmailAddress,
    GoogleNickname,
    GooglePerson,
    GooglePersonEvent,
    GooglePhoneNumber,
)
from group_naming import group_tag_segments, sanitize_tag_segment
from group_translator import GoogleGroupNameTranslator

logger = structlog.get_logger()

# What a Google import may change: the fields this transformer maps from the
# personFields the client requests. Anything else on the contact - the avatar
# another integration set, date types Google cannot hold - keeps its value.
GOOGLE_CONTACT_SYNC_SCOPE = ContactSyncScope(
    fields=frozenset(
        {
            ContactSyncField.FIRST_NAME,
            ContactSyncField.LAST_NAME,
            ContactSyncField.MIDDLE_NAME,
            ContactSyncField.NICK_NAME,
            ContactSyncField.COMPANY,
            ContactSyncField.JOB_TITLE,
            ContactSyncField.IS_FAVOURITE,
            ContactSyncField.METHODS,
            ContactSyncField.ADDRESSES,
            ContactSyncField.NOTES,
            ContactSyncField.TAGS,
        }
    ),
    important_date_types=frozenset(
        {ImportantDateType.BIRTHDAY, ImportantDateType.MARRIAGE_ANNIVERSARY}
    ),
)


class GoogleContactTransformer:
    """
    Transforms Google People API contacts to internal Contact entities.

    Handles the conversion of Google's contact format to our domain model,
    including proper mapping of names, contact methods, addresses, and metadata.
    """

    def __init__(
        self,
        *,
        user_id: str,
        default_country: str | None = None,
        translator: GoogleGroupNameTranslator | None = None,
    ) -> None:
        """
        Initialize the transformer.

        Args:
            user_id: The syncing user, stamped as the owner of every contact built.
            default_country: The syncing user's default country, the last
                resort for an address with no country (see ``address_country``).
            translator: Translator for Google Contact Groups. If None, an empty one is used.
        """
        self.user_id = user_id
        self.default_country = default_country
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

        first_name, last_name, middle_name = self._extract_names(google_person.names)
        chosen_nickname = select_nickname(google_person.nicknames)
        nick_name = (
            chosen_nickname.value.strip()
            if chosen_nickname and chosen_nickname.value
            else None
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
            user_id=self.user_id,
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

        # Addresses, notes: use None when Google provides no data so that
        # locally-managed data is preserved on sync updates. The event's
        # ``empty_at_source`` lets the backend clear addresses Google held at
        # the last sync and has deleted since (#1909).
        transformed_addresses = self._transform_addresses(
            google_person.addresses,
            fallback_country=self.address_fallback_country(google_person),
        )
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
    ) -> tuple[str | None, str | None, str | None]:
        """Extract given, family and middle names from Google names array."""
        if not names:
            return None, None, None

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
        )

    def _transform_email_addresses(
        self, email_addresses: list[GoogleEmailAddress]
    ) -> list[ContactMethod]:
        """Transform Google email addresses to ContactMethod entities."""
        return [m for m in map(import_email, email_addresses) if m is not None]

    def _transform_phone_numbers(
        self, phone_numbers: list[GooglePhoneNumber]
    ) -> list[ContactMethod]:
        """Transform Google phone numbers to ContactMethod entities."""
        return [m for m in map(import_phone, phone_numbers) if m is not None]

    def skipped_addresses(self, google_person: GooglePerson) -> list[SkippedAddress]:
        """The person's addresses the import leaves out for review (#1820).

        Judged in the country each is imported with, so a countryless "London"
        given AU by the fallback is reported, not imported.
        """
        fallback_country = self.address_fallback_country(google_person)
        return [
            skipped
            for address in google_person.addresses
            if (skipped := skipped_address(address, fallback_country)) is not None
        ]

    def address_fallback_country(self, google_person: GooglePerson) -> str | None:
        """The country this person's countryless addresses are imported with.

        ``None`` unless an address actually takes it (a street, no country of
        its own): the pull records this on the link, and the push merge owns a
        countryless address only when the recorded pull gave it a country, so
        one added in Google since is kept until it is pulled (#1820).
        """
        if not any(
            _street_line_1(address) and not getattr(address, "country_code", None)
            for address in google_person.addresses
        ):
            return None
        return resolve_address_country(
            google_person.phone_numbers, self.default_country
        )

    def _transform_addresses(
        self, addresses: list[GoogleAddress], fallback_country: str | None = None
    ) -> list[ContactAddress]:
        """Transform Google addresses to ContactAddress entities.

        An address imported with ``fallback_country`` is dropped when Google
        also holds it, every part and the country the same, with a country of
        its own: a push before #1820 sent the local copy back beside Google's
        countryless original.
        """
        imported = [
            (bool(getattr(address, "country_code", None)), contact_address)
            for address in addresses
            if (contact_address := import_address(address, fallback_country))
        ]
        held_with_country = {
            _address_key(contact_address): contact_address
            for has_country, contact_address in imported
            if has_country
        }
        transformed: list[ContactAddress] = []
        for has_country, contact_address in imported:
            twin = (
                None
                if has_country
                else held_with_country.get(_address_key(contact_address))
            )
            if twin is None:
                transformed.append(contact_address)
            elif contact_address.is_primary:
                # The dropped copy was the chosen one; its twin carries that on.
                twin.is_primary = True
        return transformed

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
        case-insensitively (lower(), matching the backend's LOWER(name) tag
        identity) — case-variant group names must collapse to a single tag.
        """
        tags: list[Tag] = []
        seen_names: set[str] = set()

        for membership in memberships:
            chain = self._create_tags_from_membership(membership)
            for tag in chain:
                lower_name = tag.name.value.lower()
                if lower_name not in seen_names:
                    seen_names.add(lower_name)
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

        # Split on '/' for hierarchy. The push keys groups by the same path
        # (group_naming.group_tag_path), so the two must stay one function.
        tags: list[Tag] = []
        for segment in group_tag_segments(name_str):
            try:
                tag = Tag(name=TagName(segment))
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
        """Sanitize one hierarchy segment to make it valid for TagName."""
        return sanitize_tag_segment(name)

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
            company = selected_org.name.strip() or None

        job_title = None
        if hasattr(selected_org, "title") and selected_org.title:
            job_title = selected_org.title.strip() or None

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

        The list is authoritative for the date types Google sync owns (see
        ``GOOGLE_CONTACT_SYNC_SCOPE``): an empty one clears them, and the sync
        scope keeps every other local date type. None - Google holds an owned
        date, but none could be read - leaves the local dates alone.
        """
        birthday_dates = self._transform_birthdays(birthdays)
        event_dates = self._transform_events(events)
        transformed_dates = birthday_dates + event_dates

        holds_owned_date = bool(birthdays) or any(
            event.type is not None and event.type.lower() in self._GOOGLE_EVENT_TYPE_MAP
            for event in events
        )
        if not transformed_dates and holds_owned_date:
            return None

        return transformed_dates

    def _transform_birthdays(
        self, birthdays: list[GoogleBirthday]
    ) -> list[ImportantDate]:
        """Transform Google birthday entries to ImportantDate entities."""
        return [b for b in map(import_birthday, birthdays) if b is not None]

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


# ── Per-entry import ────────────────────────────────────────────────────
#
# Whether one Google entry becomes part of the local contact. The push merge
# (``person_merge.py``) asks the same functions, so an entry a push treats as
# owned is exactly one the import reads: whatever these reject, the push keeps
# in Google (#1788).


def select_nickname(nicknames: list[GoogleNickname]) -> GoogleNickname | None:
    """The primary nickname, else the first one with a value.

    The contact holds one nickname; the push sends it back in that one's place.
    """
    values = [n for n in nicknames if n.value and n.value.strip()]
    primary = next((n for n in values if n.metadata.primary), None)
    return primary or (values[0] if values else None)


def import_email(email: GoogleEmailAddress) -> ContactMethod | None:
    """The email as a contact method, or None when it is not a valid one."""
    return _import_contact_method(email, MethodType.EMAIL, email.value)


def import_phone(phone: GooglePhoneNumber) -> ContactMethod | None:
    """The phone as a contact method, read from its canonical form when set."""
    return _import_contact_method(
        phone, MethodType.PHONE, phone.canonical_form or phone.value
    )


def import_address(
    address: GoogleAddress, fallback_country: str | None = None
) -> ContactAddress | None:
    """The address, or None when inbound cannot import it (see #1820).

    ``fallback_country`` stands in for a missing ``countryCode``; resolve it
    with ``address_country.resolve_address_country``. None is returned without
    a street or a country, or for an AU/US/CA region naming no state, province
    or territory - left out for the user to review (:func:`skipped_address`),
    and so never owned by a push. A recognised region is imported as its code
    ("New South Wales" -> "NSW").
    """
    street_line_1 = _street_line_1(address)
    country_code = getattr(address, "country_code", None) or fallback_country
    if not street_line_1 or not country_code:
        return None
    region = getattr(address, "region", None)
    if is_unrecognised_region(country_code, region):
        return None
    try:
        return ContactAddress(
            street_line_1=street_line_1,
            country_code=country_code,
            street_line_2=getattr(address, "extended_address", None),
            locality=getattr(address, "city", None),
            region=normalise_region(country_code, region),
            postal_code=getattr(address, "postal_code", None),
            is_primary=_is_primary_field(address),
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


def skipped_address(
    address: GoogleAddress, fallback_country: str | None = None
) -> SkippedAddress | None:
    """The address as reported for review, when its region is unrecognised.

    Judged in the country :func:`import_address` would give it, which the
    report carries.
    """
    street_line_1 = _street_line_1(address)
    country_code = getattr(address, "country_code", None) or fallback_country
    region = getattr(address, "region", None)
    if not street_line_1 or not country_code:
        return None
    if not is_unrecognised_region(country_code, region):
        return None
    return SkippedAddress(
        street_line_1=street_line_1,
        street_line_2=getattr(address, "extended_address", None),
        locality=getattr(address, "city", None),
        region=region,
        postal_code=getattr(address, "postal_code", None),
        country_code=country_code,
        reason="unrecognised_region",
    )


def _street_line_1(address: GoogleAddress) -> str | None:
    """The street, or the formatted address when Google gives no street."""
    street = getattr(address, "street_address", None)
    if not street and hasattr(address, "formatted_value"):
        street = address.formatted_value
    return street


def import_birthday(birthday: GoogleBirthday) -> ImportantDate | None:
    """The birthday's date, or None when it has no usable date (text only)."""
    if birthday.date is None:
        return None
    return GoogleContactTransformer._google_date_to_important_date(
        birthday.date, ImportantDateType.BIRTHDAY
    )


def _import_contact_method(
    entry: GoogleEmailAddress | GooglePhoneNumber,
    method_type: MethodType,
    value: str | None,
) -> ContactMethod | None:
    """A validated contact method, or None for a missing or invalid value."""
    if not value:
        return None
    label = entry.formatted_type or entry.type or None
    try:
        return ContactMethod(
            method_type=method_type,
            value=value,
            label=label,
            is_primary=_is_primary_field(entry),
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


def _address_key(address: ContactAddress) -> tuple[str, ...]:
    """Every part of an imported address, case and spacing aside."""
    parts = (
        address.street_line_1,
        address.street_line_2,
        address.locality,
        address.region,
        address.postal_code,
        address.country_code,
    )
    return tuple(" ".join((part or "").split()).casefold() for part in parts)


def _is_primary_field(field_value: Any) -> bool:
    """Whether a Google field is marked as primary."""
    metadata = getattr(field_value, "metadata", None)
    return bool(getattr(metadata, "primary", False))
