"""Unit tests for the shared entity-tag helpers.

These cover the parts of optimistic concurrency that cannot be observed from an
integration test: the backend's integration fixture runs every request inside
one shared transaction and Postgres' ``now()`` is the *transaction* timestamp,
so a real write in a test does not move ``updated_at``. "The tag changes when
the row changes" is therefore asserted here, against the function itself.
"""

from datetime import UTC, datetime, timedelta

import pytest

from core_shared.etag import (
    etag_matches,
    normalise_etag,
    parse_if_match,
    resource_etag,
)
from core_shared.exceptions import PreconditionFailedError

UPDATED_AT = datetime(2026, 8, 23, 4, 11, 9, 412873, tzinfo=UTC)


class TestResourceEtag:
    """The token derived from a resource's last-modified timestamp."""

    def test_is_stable_for_the_same_version(self) -> None:
        first = resource_etag("journals", 42, UPDATED_AT)
        second = resource_etag("journals", 42, UPDATED_AT)

        assert first == second

    def test_is_a_quoted_strong_tag(self) -> None:
        etag = resource_etag("journals", 42, UPDATED_AT)

        assert etag is not None
        assert etag.startswith('"')
        assert etag.endswith('"')
        assert not etag.startswith("W/")

    def test_changes_when_the_row_is_written(self) -> None:
        """A later ``updated_at`` must produce a different tag.

        This is the property the whole feature rests on — without it a stale
        write would pass its own precondition.
        """
        before = resource_etag("journals", 42, UPDATED_AT)
        after = resource_etag("journals", 42, UPDATED_AT + timedelta(microseconds=1))

        assert before != after

    def test_differs_across_resource_types_and_ids(self) -> None:
        """Two resources updated in the same transaction must not share a tag.

        ``now()`` is the transaction timestamp, so a journal and a contact
        written together carry byte-identical ``updated_at`` values; only the
        type and id keep their tags apart.
        """
        journal = resource_etag("journals", 42, UPDATED_AT)
        same_id_other_type = resource_etag("contacts", 42, UPDATED_AT)
        other_id = resource_etag("journals", 43, UPDATED_AT)

        assert journal != same_id_other_type
        assert journal != other_id

    def test_is_none_when_the_version_is_unknown(self) -> None:
        """No ``updated_at`` means no version to guard, not a tag over ``None``."""
        assert resource_etag("journals", 42, None) is None


class TestNormaliseEtag:
    """Comparison strips the framing a proxy may have added."""

    @pytest.mark.parametrize(
        "raw",
        ['"abc123"', 'W/"abc123"', 'w/"abc123"', '  "abc123"  ', "abc123"],
    )
    def test_reduces_to_the_bare_token(self, raw: str) -> None:
        assert normalise_etag(raw) == "abc123"


class TestParseIfMatch:
    """Reading the precondition off an ``If-Match`` header."""

    def test_absent_header_is_no_precondition(self) -> None:
        assert parse_if_match(None) is None

    def test_single_tag(self) -> None:
        assert parse_if_match('"abc123"') == ['"abc123"']

    def test_list_of_tags(self) -> None:
        assert parse_if_match('"abc", W/"def" , "ghi"') == ['"abc"', 'W/"def"', '"ghi"']

    def test_wildcard(self) -> None:
        assert parse_if_match("*") == ["*"]

    def test_empty_header_matches_nothing(self) -> None:
        """An empty ``If-Match`` is a client bug, and it fails closed.

        The caller asked for a guarded write; silently performing an unguarded
        one would hand back a 200 for a guarantee that was never checked.
        """
        assert parse_if_match("") == []
        assert parse_if_match("   ") == []


class TestEtagMatches:
    """Whether a parsed precondition permits the write."""

    def test_no_precondition_always_matches(self) -> None:
        assert etag_matches('"abc"', None) is True

    def test_matching_tag(self) -> None:
        assert etag_matches('"abc"', ['"abc"']) is True

    def test_matching_tag_among_several(self) -> None:
        assert etag_matches('"abc"', ['"zzz"', '"abc"']) is True

    def test_stale_tag(self) -> None:
        assert etag_matches('"abc"', ['"stale"']) is False

    def test_weak_tag_still_matches(self) -> None:
        """A compressing proxy may weaken the tag it forwarded to the client.

        Every tag this system mints is strong, so a weak echo of one names the
        same version; rejecting it would 412 a caller that did nothing wrong.
        """
        assert etag_matches('"abc"', ['W/"abc"']) is True

    def test_wildcard_matches_any_version(self) -> None:
        assert etag_matches('"abc"', ["*"]) is True

    def test_wildcard_matches_a_resource_with_no_known_version(self) -> None:
        """``*`` asks only that the resource exist, which the 404 check settled."""
        assert etag_matches(None, ["*"]) is True

    def test_empty_precondition_matches_nothing(self) -> None:
        assert etag_matches('"abc"', []) is False

    def test_unknown_current_version_cannot_satisfy_a_specific_tag(self) -> None:
        assert etag_matches(None, ['"abc"']) is False


class TestPreconditionFailedError:
    """The refusal both surfaces render."""

    def test_is_a_412(self) -> None:
        error = PreconditionFailedError("journals", 42, '"abc"')

        assert error.status_code == 412

    def test_message_names_the_resource_and_the_way_out(self) -> None:
        error = PreconditionFailedError("journals", 42, '"abc"')

        assert "journals" in error.message
        assert "42" in error.message
        assert "re-read" in error.message.lower()

    def test_meta_carries_the_current_tag_so_a_client_can_recover(self) -> None:
        meta = PreconditionFailedError("contacts", 7, '"current"').error_meta()

        assert meta == {
            "resource_type": "contacts",
            "resource_id": "7",
            "current_etag": '"current"',
        }

    def test_meta_is_json_serialisable_when_the_version_is_unknown(self) -> None:
        meta = PreconditionFailedError("contacts", 7, None).error_meta()

        assert meta is not None
        assert meta["current_etag"] is None
