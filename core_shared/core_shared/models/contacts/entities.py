"""Domain entities for the contacts domain."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, StrEnum

from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.contacts.value_objects import (
    Address,
    Email,
    PhoneNumber,
    TagName,
)


class SummaryStatus(Enum):
    """Enumeration for AI-generated summary statuses."""

    PENDING = "pending"
    GENERATING = "generating"
    GENERATED = "generated"
    FAILED = "failed"
    DISABLED = "disabled"

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


class SummaryDisabledReason(StrEnum):
    """Why AI summary generation is disabled for a contact.

    ``USER`` is the user's own choice and is sticky: nothing automatic turns it
    back on. ``LOW_ACTIVITY`` is the generator pausing a contact with too little
    recent activity; it is re-evaluated whenever a refresh is triggered, so the
    summary resumes once activity picks up.
    """

    USER = "user"
    LOW_ACTIVITY = "low_activity"


class MethodType(Enum):
    """Enumeration for contact method types."""

    EMAIL = "email"
    PHONE = "phone"

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


@dataclass
class Tag:
    """Tag entity with hierarchical support."""

    name: TagName
    id: int | None = None
    parent_id: int | None = None
    color: str | None = None
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate tag properties."""
        if self.color and not self.color.startswith("#"):
            raise ValueError("Color must be a hex color code starting with #")

        if self.color and len(self.color) != 7:
            raise ValueError(
                "Color must be a 7-character hex color code (e.g., #FF0000)"
            )


def _reject_archived_primary(is_primary: bool, is_archived: bool, kind: str) -> None:
    """An archived value is out of use, so it can never be the primary one."""
    if is_primary and is_archived:
        raise ValueError(f"An archived {kind} cannot be primary")


@dataclass
class ContactMethod:
    """Contact method entity for email and phone."""

    method_type: MethodType
    value: str
    contact_id: int
    id: int | None = None
    label: str | None = None  # 'work', 'home', 'mobile'
    is_primary: bool = False
    # No longer in use, but kept for matching and reference. Never primary and
    # never synced out to a provider.
    is_archived: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate contact method."""
        _reject_archived_primary(self.is_primary, self.is_archived, "contact method")
        if not isinstance(self.method_type, MethodType):
            raise ValueError(f"Invalid method type: {self.method_type}")

        # Validate the value based on type
        if self.method_type == MethodType.EMAIL:
            Email(self.value)  # This will raise if invalid
        elif self.method_type == MethodType.PHONE:
            PhoneNumber(self.value)  # This will raise if invalid

        if self.label and len(self.label) > 50:
            raise ValueError("Label cannot exceed 50 characters")


@dataclass
class ContactAddress:
    """Contact address entity with structured international format."""

    street_line_1: str
    country_code: str
    contact_id: int
    id: int | None = None
    label: str | None = None  # 'home', 'work', 'billing'
    street_line_2: str | None = None
    locality: str | None = None
    region: str | None = None
    postal_code: str | None = None
    is_primary: bool = False
    # See ContactMethod.is_archived.
    is_archived: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate contact address."""
        _reject_archived_primary(self.is_primary, self.is_archived, "contact address")
        # Create Address value object to validate
        from .value_objects import CountryCode

        Address(
            street_line_1=self.street_line_1,
            country_code=CountryCode(self.country_code),
            street_line_2=self.street_line_2,
            locality=self.locality,
            region=self.region,
            postal_code=self.postal_code,
        )

        if self.label and len(self.label) > 50:
            raise ValueError("Label cannot exceed 50 characters")

    def to_address_value_object(self) -> Address:
        """Convert to Address value object."""
        from .value_objects import CountryCode

        return Address(
            street_line_1=self.street_line_1,
            country_code=CountryCode(self.country_code),
            street_line_2=self.street_line_2,
            locality=self.locality,
            region=self.region,
            postal_code=self.postal_code,
        )


@dataclass
class ContactNote:
    """Contact note entity with timestamps."""

    content: str
    contact_id: int
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate contact note."""
        if not self.content.strip():
            raise ValueError("Note content cannot be empty")


@dataclass
class ImportantDate:
    """Important date entity associated with a contact."""

    contact_id: int
    date_type: ImportantDateType
    precision: DatePrecision

    # Nullable date components based on precision
    year: int | None = None
    month: int | None = None
    day: int | None = None

    # Foreign key and relationship to custom date type
    custom_date_type_id: int | None = None
    custom_date_type_name: str | None = None

    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate important date precision and constraints."""
        # 1. Component range validation
        if self.month is not None and not (1 <= self.month <= 12):
            raise ValueError("Month must be between 1 and 12")

        if self.day is not None and not (1 <= self.day <= 31):
            raise ValueError("Day must be between 1 and 31")

        # 2. Precision consistency validation
        if self.precision == DatePrecision.FULL:
            if self.year is None or self.month is None or self.day is None:
                raise ValueError("Full precision requires year, month, and day")

        elif self.precision == DatePrecision.DAY_MONTH:
            if self.month is None or self.day is None:
                raise ValueError("Day/Month precision requires month and day")
            if self.year is not None:
                self.year = None  # Ensure year is null for this precision

        elif self.precision == DatePrecision.YEAR:
            if self.year is None:
                raise ValueError("Year precision requires year")
            if self.month is not None or self.day is not None:
                self.month = None
                self.day = None  # Ensure month/day are null for this precision

        # 3. Custom type validation
        if self.date_type == ImportantDateType.CUSTOM:
            if self.custom_date_type_id is None:
                raise ValueError(
                    "custom_date_type_id is required for custom date types"
                )
        else:
            if self.custom_date_type_id is not None:
                raise ValueError(
                    "custom_date_type_id should only be set for custom date types"
                )


@dataclass
class ContactSummary:
    """AI-generated interaction summary for a contact."""

    contact_id: int
    id: int | None = None
    summary_text: str | None = None
    follow_up_suggestions: list[str] = field(default_factory=list)
    status: SummaryStatus = SummaryStatus.PENDING
    is_disabled: bool = False
    disabled_reason: SummaryDisabledReason | None = None
    is_user_override: bool = False
    user_override_text: str | None = None
    generated_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Reject a disabled flag and reason that disagree."""
        if self.is_disabled != (self.disabled_reason is not None):
            raise ValueError(
                "disabled_reason must be set exactly when is_disabled is True"
            )

    @property
    def is_user_disabled(self) -> bool:
        """Whether the user disabled generation (sticky, unlike an auto-pause)."""
        return self.disabled_reason == SummaryDisabledReason.USER

    def disable(self, reason: SummaryDisabledReason) -> None:
        """Disable generation for ``reason``, moving the status to DISABLED."""
        self.is_disabled = True
        self.disabled_reason = reason
        self.status = SummaryStatus.DISABLED

    def enable(self) -> None:
        """Clear the disabled flag and reason; the caller decides the new status."""
        self.is_disabled = False
        self.disabled_reason = None

    def get_display_text(self) -> str | None:
        """Get the text to display for this summary.

        Returns user override text if set, otherwise AI-generated text
        only when status is GENERATED.
        Returns None if summary is not yet generated, is disabled, or failed.
        """
        if self.is_disabled:
            return None
        if self.is_user_override and self.user_override_text:
            return self.user_override_text
        if self.status != SummaryStatus.GENERATED:
            return None
        return self.summary_text


@dataclass
class Contact:
    """Contact aggregate root entity.

    ``user_id`` names the contact's owner: set when the contact is created and
    never changed.
    """

    first_name: str
    user_id: str
    id: int | None = None
    last_name: str | None = None
    middle_name: str | None = None
    nick_name: str | None = None
    company: str | None = None
    job_title: str | None = None
    photo_url: str | None = None
    is_favourite: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Related entities (loaded separately)
    methods: list[ContactMethod] | None = None
    addresses: list[ContactAddress] | None = None
    notes: list[ContactNote] | None = None
    tags: list[Tag] | None = None
    relationships: list[ContactRelationship] | None = None
    important_dates: list[ImportantDate] | None = None
    summary: ContactSummary | None = None

    def __post_init__(self) -> None:
        """Validate contact."""
        if not self.first_name.strip():
            raise ValueError("First name is required")

        # Validate name lengths
        if len(self.first_name) > 100:
            raise ValueError("First name cannot exceed 100 characters")

        if self.last_name and len(self.last_name) > 100:
            raise ValueError("Last name cannot exceed 100 characters")

        if self.middle_name and len(self.middle_name) > 100:
            raise ValueError("Middle name cannot exceed 100 characters")

        if self.nick_name and len(self.nick_name) > 100:
            raise ValueError("Nick name cannot exceed 100 characters")

        if self.company and len(self.company) > 200:
            raise ValueError("Company cannot exceed 200 characters")

        if self.job_title and len(self.job_title) > 200:
            raise ValueError("Job title cannot exceed 200 characters")

    def get_full_name(self) -> str:
        """Get formatted full name."""
        parts = [self.first_name]

        if self.middle_name:
            parts.append(self.middle_name)

        if self.last_name:
            parts.append(self.last_name)

        return " ".join(parts)

    def get_display_name(self) -> str:
        """Get display name (nick name if available, otherwise full name)."""
        if self.nick_name:
            return self.nick_name
        return self.get_full_name()

    def get_primary_email(self) -> str | None:
        """Get primary email address."""
        if self.methods:
            for method in self.methods:
                if method.method_type == MethodType.EMAIL and method.is_primary:
                    return method.value
        return None

    def get_primary_phone(self) -> str | None:
        """Get primary phone number."""
        if self.methods:
            for method in self.methods:
                if method.method_type == MethodType.PHONE and method.is_primary:
                    return method.value
        return None

    def get_primary_address(self) -> ContactAddress | None:
        """Get primary address."""
        if self.addresses:
            for address in self.addresses:
                if address.is_primary:
                    return address
        return None

    def get_birthday(self) -> ImportantDate | None:
        """Get birthday if available."""
        if self.important_dates:
            for date in self.important_dates:
                if date.date_type == ImportantDateType.BIRTHDAY:
                    return date
        return None

    def add_tag(self, tag: Tag) -> None:
        """Add a tag to the contact."""
        if self.tags is None:
            self.tags = []

        # Check if tag already exists
        for existing_tag in self.tags:
            if existing_tag.id == tag.id:
                return  # Tag already exists

        # Check tag limit
        if len(self.tags) >= 25:
            raise ValueError("Contact cannot have more than 25 tags")

        self.tags.append(tag)

    def remove_tag(self, tag_id: int) -> None:
        """Remove a tag from the contact."""
        if self.tags is not None:
            self.tags = [tag for tag in self.tags if tag.id != tag_id]

    def toggle_favourite(self) -> None:
        """Toggle the favourite status of the contact."""
        self.is_favourite = not self.is_favourite

    def set_favourite(self, is_favourite: bool) -> None:
        """Set the favourite status of the contact."""
        self.is_favourite = is_favourite


class RelationshipType(Enum):
    """Enumeration for contact relationship types."""

    PARTNER = "partner"
    CHILD = "child"
    PARENT = "parent"
    SIBLING = "sibling"
    FRIEND = "friend"
    COLLEAGUE = "colleague"
    FAMILY = "family"
    OTHER = "other"

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value

    def get_inverse_type(self) -> RelationshipType:
        """Get the inverse relationship type for bidirectional relationships."""
        inverse_map = {
            RelationshipType.PARENT: RelationshipType.CHILD,
            RelationshipType.CHILD: RelationshipType.PARENT,
            RelationshipType.PARTNER: RelationshipType.PARTNER,
            RelationshipType.SIBLING: RelationshipType.SIBLING,
            RelationshipType.FRIEND: RelationshipType.FRIEND,
            RelationshipType.COLLEAGUE: RelationshipType.COLLEAGUE,
            RelationshipType.FAMILY: RelationshipType.FAMILY,
            RelationshipType.OTHER: RelationshipType.OTHER,
        }
        return inverse_map[self]


@dataclass
class ContactRelationship:
    """Contact relationship entity representing relationships between contacts or to the user.

    ``relationship_type`` is what the to-side (``to_contact`` or the user) is to
    ``from_contact``: a PARENT row from A to B means B is A's parent, which the UI
    shows on A's page as "Parent — B".
    """

    from_contact_id: int
    to_contact_id: int | None
    relationship_type: RelationshipType
    id: int | None = None
    from_contact_name: str | None = None
    to_contact_name: str | None = None
    to_user: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate contact relationship."""
        from core_shared.models.contacts.exceptions import ContactValidationError

        if self.to_user:
            # User-targeted relationship: to_contact_id must be None
            if self.to_contact_id is not None:
                raise ContactValidationError(
                    "relationship",
                    "to_contact_id must be None when to_user is True",
                )
            # from_contact_id must still be positive
            if self.from_contact_id <= 0:
                raise ContactValidationError(
                    "relationship", "from_contact_id must be positive"
                )
        else:
            # Contact-to-contact relationship: to_contact_id is required
            if self.to_contact_id is None:
                raise ContactValidationError(
                    "relationship",
                    "to_contact_id is required when to_user is False",
                )
            # Prevent self-relationships
            if self.from_contact_id == self.to_contact_id:
                raise ContactValidationError(
                    "relationship",
                    "Contact cannot have a relationship with itself",
                )
            # Ensure positive contact IDs
            if self.from_contact_id <= 0 or self.to_contact_id <= 0:
                raise ContactValidationError(
                    "relationship", "Contact IDs must be positive"
                )

    def __eq__(self, other: object) -> bool:
        """Check equality based on contact IDs, relationship type, and to_user flag."""
        if not isinstance(other, ContactRelationship):
            return False
        return (
            self.from_contact_id == other.from_contact_id
            and self.to_contact_id == other.to_contact_id
            and self.relationship_type == other.relationship_type
            and self.to_user == other.to_user
        )

    def get_inverse_type(self) -> RelationshipType:
        """Get the inverse relationship type for bidirectional relationships."""
        return self.relationship_type.get_inverse_type()

    def from_perspective(self, contact_id: int) -> tuple[int | None, RelationshipType]:
        """Return the other party's id and what they are to ``contact_id``.

        The other party's id is None when it is the user.
        """
        if self.to_user or self.from_contact_id == contact_id:
            return self.to_contact_id, self.relationship_type
        return self.from_contact_id, self.get_inverse_type()

    def is_bidirectional(self) -> bool:
        """Check if this relationship type should be bidirectional."""
        bidirectional_types = {
            RelationshipType.PARTNER,
            RelationshipType.SIBLING,
            RelationshipType.FRIEND,
            RelationshipType.COLLEAGUE,
            RelationshipType.FAMILY,
        }
        return self.relationship_type in bidirectional_types
