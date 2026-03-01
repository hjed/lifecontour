"""
Pydantic models for Google People API response structures.

These models match the Google People API response format to provide
type safety and validation when processing API responses.
"""

from typing import Any

from pydantic import BaseModel, Field


class GoogleFieldMetadata(BaseModel):
    """Metadata for Google People API fields."""

    primary: bool = False
    source_primary: bool = Field(default=False, alias="sourcePrimary")
    verified: bool = Field(default=False)
    source: dict[str, Any] = Field(default_factory=dict)


class GoogleName(BaseModel):
    """Google People API name structure."""

    metadata: GoogleFieldMetadata = Field(default_factory=GoogleFieldMetadata)
    display_name: str | None = Field(default=None, alias="displayName")
    family_name: str | None = Field(default=None, alias="familyName")
    given_name: str | None = Field(default=None, alias="givenName")
    middle_name: str | None = Field(default=None, alias="middleName")
    honorific_prefix: str | None = Field(default=None, alias="honorificPrefix")
    honorific_suffix: str | None = Field(default=None, alias="honorificSuffix")
    phonetic_family_name: str | None = Field(default=None, alias="phoneticFamilyName")
    phonetic_given_name: str | None = Field(default=None, alias="phoneticGivenName")
    phonetic_middle_name: str | None = Field(default=None, alias="phoneticMiddleName")
    phonetic_honorific_prefix: str | None = Field(
        default=None, alias="phoneticHonorificPrefix"
    )
    phonetic_honorific_suffix: str | None = Field(
        default=None, alias="phoneticHonorificSuffix"
    )


class GoogleEmailAddress(BaseModel):
    """Google People API email address structure."""

    metadata: GoogleFieldMetadata = Field(default_factory=GoogleFieldMetadata)
    value: str
    type: str | None = None
    formatted_type: str | None = Field(default=None, alias="formattedType")
    display_name: str | None = Field(default=None, alias="displayName")


class GooglePhoneNumber(BaseModel):
    """Google People API phone number structure."""

    metadata: GoogleFieldMetadata = Field(default_factory=GoogleFieldMetadata)
    value: str
    canonical_form: str | None = Field(default=None, alias="canonicalForm")
    type: str | None = None
    formatted_type: str | None = Field(default=None, alias="formattedType")


class GoogleAddress(BaseModel):
    """Google People API address structure."""

    metadata: GoogleFieldMetadata = Field(default_factory=GoogleFieldMetadata)
    formatted_value: str | None = Field(default=None, alias="formattedValue")
    type: str | None = None
    formatted_type: str | None = Field(default=None, alias="formattedType")
    po_box: str | None = Field(default=None, alias="poBox")
    street_address: str | None = Field(default=None, alias="streetAddress")
    extended_address: str | None = Field(default=None, alias="extendedAddress")
    city: str | None = None
    region: str | None = None
    postal_code: str | None = Field(default=None, alias="postalCode")
    country: str | None = None
    country_code: str | None = Field(default=None, alias="countryCode")


class GoogleOrganization(BaseModel):
    """Google People API organization structure."""

    metadata: GoogleFieldMetadata = Field(default_factory=GoogleFieldMetadata)
    type: str | None = None
    formatted_type: str | None = Field(default=None, alias="formattedType")
    start_date: dict[str, Any] | None = Field(default=None, alias="startDate")
    end_date: dict[str, Any] | None = Field(default=None, alias="endDate")
    current: bool | None = None
    name: str | None = None
    phonetic_name: str | None = Field(default=None, alias="phoneticName")
    department: str | None = None
    title: str | None = None
    job_description: str | None = Field(default=None, alias="jobDescription")
    symbol: str | None = None
    domain: str | None = None
    location: str | None = None


class GoogleBirthday(BaseModel):
    """Google People API birthday structure."""

    metadata: GoogleFieldMetadata = Field(default_factory=GoogleFieldMetadata)
    date: dict[str, Any] | None = None
    text: str | None = None


class GoogleBiography(BaseModel):
    """Google People API biography/note structure."""

    metadata: GoogleFieldMetadata = Field(default_factory=GoogleFieldMetadata)
    value: str
    content_type: str | None = Field(default=None, alias="contentType")


class GoogleMembership(BaseModel):
    """Google People API membership structure (for contact groups/labels)."""

    metadata: GoogleFieldMetadata = Field(default_factory=GoogleFieldMetadata)
    contact_group_membership: dict[str, Any] | None = Field(
        default=None, alias="contactGroupMembership"
    )
    domain_membership: dict[str, Any] | None = Field(
        default=None, alias="domainMembership"
    )


class GooglePerson(BaseModel):
    """Google People API Person structure."""

    resource_name: str = Field(alias="resourceName")
    etag: str | None = None
    names: list[GoogleName] = Field(default_factory=list)
    nicknames: list[dict[str, Any]] = Field(default_factory=list)
    email_addresses: list[GoogleEmailAddress] = Field(
        default_factory=list, alias="emailAddresses"
    )
    phone_numbers: list[GooglePhoneNumber] = Field(
        default_factory=list, alias="phoneNumbers"
    )
    addresses: list[GoogleAddress] = Field(default_factory=list)
    organizations: list[GoogleOrganization] = Field(default_factory=list)
    birthdays: list[GoogleBirthday] = Field(default_factory=list)
    biographies: list[GoogleBiography] = Field(default_factory=list)
    memberships: list[GoogleMembership] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ListConnectionsResponse(BaseModel):
    """Google People API list connections response structure."""

    connections: list[GooglePerson] = Field(default_factory=list)
    next_page_token: str | None = Field(default=None, alias="nextPageToken")
    next_sync_token: str | None = Field(default=None, alias="nextSyncToken")
    total_people: int | None = Field(default=None, alias="totalPeople")
    total_items: int | None = Field(default=None, alias="totalItems")
