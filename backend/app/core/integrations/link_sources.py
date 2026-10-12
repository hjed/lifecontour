"""Registry of integration sources and where each one stores its entity links.

Every place that needs to know "which integrations link to journals/contacts,
under what name, and how to find the linked row" derives it from here: the
external-link helpers (how a link is displayed), the MCP tools (which
``source`` values are valid, including the displayed names an agent will have
read back), and the repositories (how to query a link by source or by the
external id). Adding a source is one entry in a registry below.
"""

from __future__ import annotations

import dataclasses
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


class AliasPolicy(StrEnum):
    """Whether a merge keeps a store's absorbed records as merged aliases.

    Every store has to say. A merge that cannot carry a source journal's
    record over as a live link on the target keeps an ``INBOUND`` record as an
    alias (``core_shared.repositories.merged_alias_repository``), so the next
    sync recognises it instead of importing it again.
    """

    # Imported from the source: losing it means the sync re-imports it.
    INBOUND = "inbound"
    # Pushed to the source (or derived from such a push): the source journal's
    # deletion undoes it upstream, so there is nothing to recognise later.
    NOT_ALIASABLE = "not_aliasable"
    # The alias table itself, read so lookups resolve an absorbed record.
    MERGED_ALIAS = "merged_alias"


@dataclass(frozen=True, kw_only=True)
class JournalLinkStore:
    """One SQL location holding links of a source to journals.

    ``from_sql`` must bring the ``journals`` table into scope as ``j`` so every
    query is scoped to the requesting user; ``journal_id_sql`` and
    ``external_id_sql`` are the expressions yielding the journal id and the
    external id **as the journal's external links expose it**.

    ``alias_policy`` has no default on purpose: a new store has to decide
    whether its records come *from* the source (see :class:`AliasPolicy`).
    The optional ``*_sql`` expressions are what a calendar store can add to an
    alias — the calendar for deleting it upstream with its journal, the
    cross-calendar identity and recurring series for recognising it.
    """

    from_sql: str
    journal_id_sql: str
    external_id_sql: str
    alias_policy: AliasPolicy
    where_sql: str = ""
    calendar_id_sql: str | None = None
    external_identity_sql: str | None = None
    recurring_event_id_sql: str | None = None


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

# The link from an imported journal to the Snipe-IT maintenance it was imported
# from, as ``l``. An import's sync row names no journal; the backend links the
# journal to the record on the synthetic maintenance calendar instead.
SNIPEIT_MAINTENANCE_IMPORT_LINK = (
    "journal_external_event_links l "
    "JOIN calendars c ON c.id = l.calendar_id "
    "AND c.integration_source = 'snipeit_maintenance'"
)
# True for the journal ``j`` unless it was imported from Snipe-IT. An imported
# journal is the record its import link names, so a push row naming it can only
# be an echo an old push created before imports stopped being pushed back: it
# is neither shown nor matched.
SNIPEIT_MAINTENANCE_NOT_IMPORTED = (
    f"NOT EXISTS (SELECT 1 FROM {SNIPEIT_MAINTENANCE_IMPORT_LINK} "
    "WHERE l.journal_id = j.id)"
)

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
                alias_policy=AliasPolicy.INBOUND,
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
                alias_policy=AliasPolicy.INBOUND,
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
                alias_policy=AliasPolicy.INBOUND,
                calendar_id_sql="l.calendar_id",
                external_identity_sql="l.external_identity",
                recurring_event_id_sql="l.recurring_event_id",
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
                alias_policy=AliasPolicy.INBOUND,
            ),
        ),
    ),
    # 'snipeit' is how a gear-checkout journal's link is displayed: the id it
    # carries is the Snipe-IT asset of a gear item on the journal, one per
    # (asset, journal) pair Snipe-IT has a checkout for.
    IntegrationSource.SNIPEIT: JournalLinkSource(
        name=IntegrationSource.SNIPEIT,
        description="Snipe-IT asset id of the gear checked out on the journal",
        stores=(
            JournalLinkStore(
                from_sql=(
                    f"{_SNIPEIT_JOURNAL_ROW} "
                    "JOIN journal_gear_usage_items gui ON gui.journal_id = j.id "
                    "JOIN sync_metadata m_asset "
                    "ON m_asset.internal_uuid = CAST(gui.gear_item_id AS VARCHAR) "
                    "AND m_asset.integration_source = 'snipeit' "
                    "AND m.external_id "
                    "= 'snipeit_checkout:' || m_asset.external_id || ':' || m.internal_uuid"
                ),
                journal_id_sql="j.id",
                external_id_sql="m_asset.external_id",
                where_sql=f"{_SNIPEIT_JOURNAL_ROW_WHERE}'snipeit_checkout'",
                alias_policy=AliasPolicy.NOT_ALIASABLE,
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
                alias_policy=AliasPolicy.NOT_ALIASABLE,
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
                where_sql=(
                    f"{_SNIPEIT_JOURNAL_ROW_WHERE}'snipeit_maintenance' "
                    f"AND {SNIPEIT_MAINTENANCE_NOT_IMPORTED}"
                ),
                alias_policy=AliasPolicy.NOT_ALIASABLE,
            ),
            # Journals imported from Snipe-IT
            JournalLinkStore(
                from_sql=(
                    f"{SNIPEIT_MAINTENANCE_IMPORT_LINK} "
                    "JOIN journals j ON j.id = l.journal_id"
                ),
                journal_id_sql="l.journal_id",
                external_id_sql="l.external_event_id",
                alias_policy=AliasPolicy.INBOUND,
                calendar_id_sql="l.calendar_id",
            ),
        ),
    ),
}


def _with_merged_alias_store(source: JournalLinkSource) -> JournalLinkSource:
    """Add the alias table to a source whose records a merge can absorb.

    A record a merge kept as an alias of the survivor still resolves to the
    survivor by its id, as it did to the journal it came from.
    """
    if not any(store.alias_policy is AliasPolicy.INBOUND for store in source.stores):
        return source
    alias_store = JournalLinkStore(
        from_sql="journal_merged_aliases a JOIN journals j ON j.id = a.journal_id",
        journal_id_sql="a.journal_id",
        external_id_sql="a.external_id",
        where_sql=f"a.integration_source = '{source.name}'",
        alias_policy=AliasPolicy.MERGED_ALIAS,
    )
    return dataclasses.replace(source, stores=(*source.stores, alias_store))


JOURNAL_LINK_SOURCES = {
    name: _with_merged_alias_store(source)
    for name, source in JOURNAL_LINK_SOURCES.items()
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


# Displayed link names that are a view of another source's store: an Immich
# album with a public share link is reported as 'immich_shared' with the same
# album UUID, so it resolves through the 'immich_album' store.
JOURNAL_SOURCE_ALIASES: dict[str, str] = {
    "immich_shared": IntegrationSource.IMMICH_ALBUM,
}


def journal_source_names() -> list[str]:
    """Every ``source`` value accepted for journal filters and lookups."""
    return sorted({*JOURNAL_LINK_SOURCES, *JOURNAL_SOURCE_ALIASES})


def contact_source_names() -> list[str]:
    """Every ``source`` value accepted for contact lookups (stored + displayed)."""
    names = {src.name for src in CONTACT_LINK_SOURCES.values()}
    names |= {src.displayed_as for src in CONTACT_LINK_SOURCES.values()}
    return sorted(names)


def resolve_journal_source(value: str) -> str:
    """Normalise a journal source name; unknown values raise with the allowed list."""
    normalized = JOURNAL_SOURCE_ALIASES.get(
        value.strip().lower(), value.strip().lower()
    )
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
