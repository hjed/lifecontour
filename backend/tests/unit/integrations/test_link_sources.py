"""The integration-source registry drives every link query and source name."""

import pytest

from app.core.integrations.link_sources import (
    CONTACT_LINK_SOURCES,
    JOURNAL_LINK_SOURCES,
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
