"""Registry of integration sources and where each one stores its entity links.

Every place that needs to know "which integrations link to journals/contacts,
under what name, and how to find the linked row" derives it from here: the
external-link helpers (how a link is displayed), the MCP tools (which
``source`` values are valid, including the displayed names an agent will have
read back), and the repositories (how to query a link by source or by the
external id). Adding a source is one entry in a registry below.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IntegrationSource(StrEnum):
    """Stored ``integration_source`` values across the link stores."""

    GOOGLE = "google"
    GOOGLE_CALENDAR = "google_calendar"
    STRAVA = "strava"
    IMMICH = "immich"
    IMMICH_ALBUM = "immich_album"
    SNIPEIT = "snipeit"
    SNIPEIT_MAINTENANCE = "snipeit_maintenance"
    SNIPEIT_CHECKOUT = "snipeit_checkout"
    FIREFLY_III = "firefly_iii"


@dataclass(frozen=True)
class JournalLinkStore:
    """One SQL location holding links of a source to journals.

    ``from_sql`` must bring the ``journals`` table into scope as ``j`` so every
    query is scoped to the requesting user; ``journal_id_sql`` and
    ``external_id_sql`` are the expressions yielding the journal id and the
    external id **as the journal's external links expose it**.
    """

    from_sql: str
    journal_id_sql: str
    external_id_sql: str
    where_sql: str = ""


@dataclass(frozen=True)
class JournalLinkSource:
    """A source an agent can name when filtering or looking up journals."""

    name: str
    description: str
    stores: tuple[JournalLinkStore, ...]


_SNIPEIT_JOURNAL_ROW = (
    "sync_metadata m JOIN journals j ON j.id = CAST(m.internal_uuid AS INTEGER)"
)
_SNIPEIT_JOURNAL_ROW_WHERE = "m.internal_uuid ~ '^[0-9]+$' AND m.integration_source = "

JOURNAL_LINK_SOURCES: dict[str, JournalLinkSource] = {
    IntegrationSource.STRAVA: JournalLinkSource(
        name=IntegrationSource.STRAVA,
        description="Strava activity id",
        stores=(
            JournalLinkStore(
                from_sql="sync_metadata m JOIN journals j ON j.id = m.internal_id",
                journal_id_sql="m.internal_id",
                external_id_sql="m.external_id",
                where_sql=(
                    "m.integration_source = 'strava' "
                    "AND m.internal_entity_type = 'journal'"
                ),
            ),
            # Activities imported before sync_metadata recorded them only have
            # the fitness column.
            JournalLinkStore(
                from_sql="journal_fitness_data f JOIN journals j ON j.id = f.journal_id",
                journal_id_sql="f.journal_id",
                external_id_sql="f.strava_activity_id",
                where_sql=(
                    "f.strava_activity_id IS NOT NULL "
                    "AND trim(f.strava_activity_id) != ''"
                ),
            ),
        ),
    ),
    IntegrationSource.GOOGLE_CALENDAR: JournalLinkSource(
        name=IntegrationSource.GOOGLE_CALENDAR,
        description="Google Calendar event id",
        stores=(
            JournalLinkStore(
                from_sql=(
                    "journal_external_event_links l "
                    "JOIN journals j ON j.id = l.journal_id "
                    "JOIN calendars c ON c.id = l.calendar_id"
                ),
                journal_id_sql="l.journal_id",
                external_id_sql="l.external_event_id",
                where_sql=(
                    "l.external_event_id IS NOT NULL "
                    "AND trim(l.external_event_id) != '' "
                    "AND c.google_calendar_id IS NOT NULL"
                ),
            ),
        ),
    ),
    IntegrationSource.IMMICH_ALBUM: JournalLinkSource(
        name=IntegrationSource.IMMICH_ALBUM,
        description="Immich album UUID",
        stores=(
            JournalLinkStore(
                from_sql="sync_metadata m JOIN journals j ON j.id = m.internal_id",
                journal_id_sql="m.internal_id",
                external_id_sql="m.external_id",
                where_sql="m.integration_source = 'immich_album'",
            ),
        ),
    ),
    # 'snipeit' is how a gear-checkout journal's link is displayed: the id it
    # carries is the Snipe-IT asset of the gear item on the journal.
    IntegrationSource.SNIPEIT: JournalLinkSource(
        name=IntegrationSource.SNIPEIT,
        description="Snipe-IT asset id of the gear checked out on the journal",
        stores=(
            JournalLinkStore(
                from_sql=(
                    f"{_SNIPEIT_JOURNAL_ROW} "
                    "JOIN journal_gear_usage_data gud ON gud.journal_id = j.id "
                    "JOIN sync_metadata m_asset "
                    "ON m_asset.internal_uuid = CAST(gud.gear_item_id AS VARCHAR) "
                    "AND m_asset.integration_source = 'snipeit'"
                ),
                journal_id_sql="j.id",
                external_id_sql="m_asset.external_id",
                where_sql=f"{_SNIPEIT_JOURNAL_ROW_WHERE}'snipeit_checkout'",
            ),
        ),
    ),
    IntegrationSource.SNIPEIT_CHECKOUT: JournalLinkSource(
        name=IntegrationSource.SNIPEIT_CHECKOUT,
        description="Snipe-IT checkout record id",
        stores=(
            JournalLinkStore(
                from_sql=_SNIPEIT_JOURNAL_ROW,
                journal_id_sql="j.id",
                external_id_sql="m.external_id",
                where_sql=f"{_SNIPEIT_JOURNAL_ROW_WHERE}'snipeit_checkout'",
            ),
        ),
    ),
    IntegrationSource.SNIPEIT_MAINTENANCE: JournalLinkSource(
        name=IntegrationSource.SNIPEIT_MAINTENANCE,
        description="Snipe-IT maintenance id",
        stores=(
            JournalLinkStore(
                from_sql=_SNIPEIT_JOURNAL_ROW,
                journal_id_sql="j.id",
                external_id_sql="m.external_id",
                where_sql=f"{_SNIPEIT_JOURNAL_ROW_WHERE}'snipeit_maintenance'",
            ),
        ),
    ),
}


@dataclass(frozen=True)
class ContactLinkSource:
    """A source that links to contacts in ``sync_metadata``."""

    name: str
    displayed_as: str
    description: str


CONTACT_LINK_SOURCES: dict[str, ContactLinkSource] = {
    IntegrationSource.GOOGLE: ContactLinkSource(
        name=IntegrationSource.GOOGLE,
        displayed_as="google_contacts",
        description="Google People resource name, e.g. 'people/c123'",
    ),
    IntegrationSource.IMMICH: ContactLinkSource(
        name=IntegrationSource.IMMICH,
        displayed_as="immich",
        description="Immich person UUID",
    ),
}


def journal_source_names() -> list[str]:
    """Every ``source`` value accepted for journal filters and lookups."""
    return sorted(JOURNAL_LINK_SOURCES)


def contact_source_names() -> list[str]:
    """Every ``source`` value accepted for contact lookups (stored + displayed)."""
    names = {src.name for src in CONTACT_LINK_SOURCES.values()}
    names |= {src.displayed_as for src in CONTACT_LINK_SOURCES.values()}
    return sorted(names)


def resolve_journal_source(value: str) -> str:
    """Normalise a journal source name; unknown values raise with the allowed list."""
    normalized = value.strip().lower()
    if normalized not in JOURNAL_LINK_SOURCES:
        allowed = ", ".join(journal_source_names())
        raise ValueError(
            f"Invalid integration_source '{value}'. Must be one of: {allowed}"
        )
    return normalized


def resolve_contact_source(value: str) -> str:
    """Map a stored or displayed contact source name to the stored name."""
    normalized = value.strip().lower()
    for source in CONTACT_LINK_SOURCES.values():
        if normalized in (source.name, source.displayed_as):
            return source.name
    allowed = ", ".join(contact_source_names())
    raise ValueError(f"Invalid source '{value}'. Must be one of: {allowed}")
