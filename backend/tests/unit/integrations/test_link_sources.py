"""The integration-source registry drives every link query and source name."""

import pytest
from core_shared.merged_alias_keys import merged_alias_key

from app.core.integrations.adapters.sql.external_record_repository import (
    external_records_sql,
)
from app.core.integrations.link_sources import (
    CONTACT_LINK_SOURCES,
    JOURNAL_LINK_SOURCES,
    AliasPolicy,
    contact_source_names,
    journal_source_names,
    resolve_contact_source,
    resolve_journal_source,
)
from app.core.journal.adapters.sql.journal_repository import _journal_link_sql


@pytest.mark.parametrize("source", sorted(JOURNAL_LINK_SOURCES))
@pytest.mark.parametrize("by_external_id", [False, True])
def test_every_journal_source_query_is_user_scoped(
    source: str, by_external_id: bool
) -> None:
    sql = _journal_link_sql(source, by_external_id=by_external_id)
    assert sql is not None
    branches = sql.split(" UNION ")
    assert len(branches) == len(JOURNAL_LINK_SOURCES[source].stores)
    for branch in branches:
        assert "j.user_id = :user_id" in branch
        assert ("= :external_id" in branch) is by_external_id


def test_unknown_journal_source_builds_nothing() -> None:
    assert _journal_link_sql("garmin", by_external_id=True) is None


def test_journal_source_resolution_lists_allowed_values() -> None:
    assert resolve_journal_source(" Strava ") == "strava"
    with pytest.raises(ValueError, match=", ".join(journal_source_names())):
        resolve_journal_source("garmin")


def test_contact_sources_accept_their_displayed_names() -> None:
    """An agent can feed back the `source` a contact's external_links report."""
    for source in CONTACT_LINK_SOURCES.values():
        assert resolve_contact_source(source.displayed_as) == source.name
        assert resolve_contact_source(source.name) == source.name
    assert "google_contacts" in contact_source_names()
    with pytest.raises(ValueError, match="google, google_contacts, immich"):
        resolve_contact_source("strava")


def test_displayed_immich_shared_link_resolves_to_the_album_store() -> None:
    """`immich_shared` is how a shared album link is displayed; it is an alias."""
    assert resolve_journal_source("immich_shared") == "immich_album"
    assert "immich_shared" in journal_source_names()


# --- Merged aliases ---------------------------------------------------------
#
# A merge keeps an absorbed *inbound* record as an alias of the survivor, so
# the next sync does not import it again. Which stores hold inbound records is
# declared on each store; these tests fix the current answers and make a new
# store's answer something someone has to write down.

# Every store, as (source, position in its stores tuple), that holds records
# imported from the source rather than pushed to it.
EXPECTED_INBOUND_STORES = {
    ("strava", 0),  # sync_metadata
    ("strava", 1),  # journal_fitness_data
    ("google_calendar", 0),
    ("immich_album", 0),
    ("snipeit_maintenance", 1),  # the import link on the synthetic calendar
}


def test_inbound_stores_are_exactly_the_imported_records() -> None:
    """Snipe-IT assets, check-outs and pushed maintenance are outbound.

    The source's own deletion undoes those upstream, so aliasing them would
    keep a record that no longer exists; and an asset belongs to no single
    journal, so an alias of one would swallow unrelated check-outs.
    """
    inbound = {
        (name, position)
        for name, source in JOURNAL_LINK_SOURCES.items()
        for position, store in enumerate(source.stores)
        if store.alias_policy is AliasPolicy.INBOUND
    }
    assert inbound == EXPECTED_INBOUND_STORES


@pytest.mark.parametrize(
    "source",
    sorted(
        {
            name
            for name, source in JOURNAL_LINK_SOURCES.items()
            if any(s.alias_policy is AliasPolicy.INBOUND for s in source.stores)
        }
    ),
)
def test_every_inbound_source_has_an_alias_key(source: str) -> None:
    """A worker naming the source must reach the alias the merge recorded."""
    key = merged_alias_key(source, "some-id")
    assert key is not None
    assert key.integration_source == source


def test_the_external_record_snapshot_reads_only_inbound_stores() -> None:
    sql = external_records_sql()
    branches = sql.split(" UNION ALL ")
    assert len(branches) == len(EXPECTED_INBOUND_STORES)
    for branch in branches:
        assert ":journal_id" in branch
    assert "snipeit_checkout" not in sql
