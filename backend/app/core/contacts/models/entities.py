"""Domain entities for the contacts domain."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .value_objects import Address, Email, PhoneNumber, TagName


class MethodType(Enum):
    """Enumeration for contact method types."""

    EMAIL = "email"
    PHONE = "phone"

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


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

    def get_inverse_type(self) -> "RelationshipType":
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


@dataclass
class ContactMethod:
    """Contact method entity for email and phone."""

    method_type: MethodType
    value: str
    contact_id: int
    id: int | None = None
    label: str | None = None  # 'work', 'home', 'mobile'
    is_primary: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate contact method."""
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
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate contact address."""
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
class Contact:
    """Contact aggregate root entity."""

    first_name: str
    id: int | None = None
    last_name: str | None = None
    middle_name: str | None = None
    nick_name: str | None = None
    is_favourite: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Related entities (loaded separately)
    methods: list[ContactMethod] = field(default_factory=list)
    addresses: list[ContactAddress] = field(default_factory=list)
    notes: list[ContactNote] = field(default_factory=list)
    tags: list[Tag] = field(default_factory=list)
    relationships: list["ContactRelationship"] = field(default_factory=list)

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
        for method in self.methods:
            if method.method_type == MethodType.EMAIL and method.is_primary:
                return method.value
        return None

    def get_primary_phone(self) -> str | None:
        """Get primary phone number."""
        for method in self.methods:
            if method.method_type == MethodType.PHONE and method.is_primary:
                return method.value
        return None

    def get_primary_address(self) -> ContactAddress | None:
        """Get primary address."""
        for address in self.addresses:
            if address.is_primary:
                return address
        return None

    def add_tag(self, tag: Tag) -> None:
        """Add a tag to the contact."""
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
        self.tags = [tag for tag in self.tags if tag.id != tag_id]

    def toggle_favourite(self) -> None:
        """Toggle the favourite status of the contact."""
        self.is_favourite = not self.is_favourite

    def set_favourite(self, is_favourite: bool) -> None:
        """Set the favourite status of the contact."""
        self.is_favourite = is_favourite


@dataclass
class ContactRelationship:
    """Contact relationship entity representing relationships between contacts."""

    from_contact_id: int
    to_contact_id: int
    relationship_type: RelationshipType
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate contact relationship."""
        # Prevent self-relationships
        if self.from_contact_id == self.to_contact_id:
            raise ValueError("Contact cannot have a relationship with itself")

        # Ensure positive contact IDs
        if self.from_contact_id <= 0 or self.to_contact_id <= 0:
            raise ValueError("Contact IDs must be positive")

    def __eq__(self, other: object) -> bool:
        """Check equality based on contact IDs and relationship type."""
        if not isinstance(other, ContactRelationship):
            return False
        return (
            self.from_contact_id == other.from_contact_id
            and self.to_contact_id == other.to_contact_id
            and self.relationship_type == other.relationship_type
        )

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
        return inverse_map[self.relationship_type]

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
