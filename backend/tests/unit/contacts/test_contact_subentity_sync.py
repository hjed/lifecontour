"""Unit tests for the contact sub-entity reconcile helpers.

These back the whole-contact save path: rather than deleting every method,
address, note and important date and re-inserting it, the save matches what
was submitted against what is stored, so an *edit* can be published as an edit
(issue #1524).
"""

import pytest
from core_shared.models.contacts.entities import (
    ContactAddress,
    ContactMethod,
    ContactNote,
    ImportantDate,
    MethodType,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)

from app.core.contacts.services.contact_subentity_sync import (
    ADDRESS_FIELDS,
    ADDRESS_PREFIX,
    IMPORTANT_DATE_FIELDS,
    METHOD_FIELDS,
    METHOD_PREFIX,
    NOTE_FIELDS,
    NOTE_PREFIX,
    diff_fields,
    important_date_key,
    prefixed,
    reconcile,
)
from app.core.history.services.history_service import (
    _SUBENTITY_FIELD_RE,
    _SUBENTITY_PREFIX_ENTITY_TYPE,
)

CONTACT_ID = 42


def _method(
    value: str,
    *,
    id: int | None = None,
    method_type: MethodType = MethodType.EMAIL,
    label: str | None = None,
    is_primary: bool = False,
) -> ContactMethod:
    return ContactMethod(
        method_type=method_type,
        value=value,
        contact_id=CONTACT_ID,
        id=id,
        label=label,
        is_primary=is_primary,
    )


def _note(content: str, *, id: int | None = None) -> ContactNote:
    return ContactNote(content=content, contact_id=CONTACT_ID, id=id)


def _address(
    street: str, *, id: int | None = None, label: str | None = None
) -> ContactAddress:
    return ContactAddress(
        street_line_1=street,
        country_code="AU",
        contact_id=CONTACT_ID,
        id=id,
        label=label,
        locality="Sydney",
        postal_code="2000",
    )


def _date(
    *,
    id: int | None = None,
    date_type: ImportantDateType = ImportantDateType.BIRTHDAY,
    year: int | None = 1990,
    month: int | None = 3,
    day: int | None = 9,
    precision: DatePrecision = DatePrecision.FULL,
) -> ImportantDate:
    return ImportantDate(
        contact_id=CONTACT_ID,
        date_type=date_type,
        precision=precision,
        year=year,
        month=month,
        day=day,
        id=id,
    )


class TestReconcileByIdentity:
    """Matching on the database id — how every REST caller arrives."""

    def test_matches_by_id_and_deletes_the_rest(self) -> None:
        stored_email = _method("old@example.com", id=1)
        stored_phone = _method("+61412345678", id=2, method_type=MethodType.PHONE)
        submitted = _method("new@example.com", id=1)

        result = reconcile([stored_email, stored_phone], [submitted])

        assert result.updates == [(stored_email, submitted)]
        assert result.deletions == [stored_phone]
        assert result.inserts == []

    def test_an_id_less_item_is_an_insert_when_there_is_no_natural_key(self) -> None:
        stored = _note("Met at the conference", id=1)
        submitted_new = _note("Follows the cricket")

        result = reconcile([stored], [stored, submitted_new])

        assert result.inserts == [submitted_new]
        assert result.updates == [(stored, stored)]
        assert result.deletions == []

    def test_an_unknown_id_is_treated_as_an_insert(self) -> None:
        """A submitted id that names no stored row cannot be an edit of it."""
        stored = _note("Met at the conference", id=1)
        submitted = _note("Follows the cricket", id=999)

        result = reconcile([stored], [submitted])

        assert result.inserts == [submitted]
        assert result.deletions == [stored]
        assert result.updates == []

    def test_an_empty_submission_deletes_everything(self) -> None:
        stored = [_note("One", id=1), _note("Two", id=2)]

        result = reconcile(stored, [])

        assert result.deletions == stored
        assert result.inserts == []
        assert result.updates == []

    def test_an_empty_store_inserts_everything(self) -> None:
        submitted = [_note("One"), _note("Two")]

        result = reconcile([], submitted)

        assert result.inserts == submitted
        assert result.deletions == []
        assert result.updates == []


class TestReconcileByNaturalKey:
    """Matching id-less items — how MCP submits important dates."""

    def test_matches_an_id_less_item_by_its_natural_key(self) -> None:
        stored = _date(id=7, year=1990)
        submitted = _date(year=1991)

        result = reconcile([stored], [submitted], natural_key=important_date_key)

        assert result.updates == [(stored, submitted)]
        assert result.inserts == []
        assert result.deletions == []

    def test_ids_are_matched_before_natural_keys(self) -> None:
        """Both passes see the whole list, so an id can claim a row a natural
        key would otherwise have taken."""
        first_birthday = _date(id=1, year=1990)
        second_birthday = _date(id=2, year=1991)
        by_id = _date(id=2, year=1992)
        by_key = _date(year=1993)

        result = reconcile(
            [first_birthday, second_birthday],
            [by_id, by_key],
            natural_key=important_date_key,
        )

        assert result.updates == [
            (second_birthday, by_id),
            (first_birthday, by_key),
        ]
        assert result.inserts == []
        assert result.deletions == []

    def test_pairs_in_order_within_one_key_group(self) -> None:
        first = _date(id=1, date_type=ImportantDateType.WORK_ANNIVERSARY, year=2011)
        second = _date(id=2, date_type=ImportantDateType.WORK_ANNIVERSARY, year=2015)
        submitted_first = _date(date_type=ImportantDateType.WORK_ANNIVERSARY, year=2012)
        submitted_second = _date(
            date_type=ImportantDateType.WORK_ANNIVERSARY, year=2016
        )

        result = reconcile(
            [first, second],
            [submitted_first, submitted_second],
            natural_key=important_date_key,
        )

        assert result.updates == [
            (first, submitted_first),
            (second, submitted_second),
        ]

    def test_a_surplus_in_a_key_group_is_an_insert(self) -> None:
        stored = _date(id=1, date_type=ImportantDateType.WORK_ANNIVERSARY, year=2011)
        submitted = _date(date_type=ImportantDateType.WORK_ANNIVERSARY, year=2011)
        surplus = _date(date_type=ImportantDateType.WORK_ANNIVERSARY, year=2015)

        result = reconcile(
            [stored], [submitted, surplus], natural_key=important_date_key
        )

        assert result.updates == [(stored, submitted)]
        assert result.inserts == [surplus]

    def test_a_shortfall_in_a_key_group_is_a_deletion(self) -> None:
        kept = _date(id=1, date_type=ImportantDateType.WORK_ANNIVERSARY, year=2011)
        dropped = _date(id=2, date_type=ImportantDateType.WORK_ANNIVERSARY, year=2015)
        submitted = _date(date_type=ImportantDateType.WORK_ANNIVERSARY, year=2012)

        result = reconcile([kept, dropped], [submitted], natural_key=important_date_key)

        assert result.updates == [(kept, submitted)]
        assert result.deletions == [dropped]

    def test_a_different_key_is_never_matched(self) -> None:
        """A birthday is not an edit of an anniversary, however alike they look."""
        stored = _date(id=1, date_type=ImportantDateType.BIRTHDAY)
        submitted = _date(date_type=ImportantDateType.WORK_ANNIVERSARY)

        result = reconcile([stored], [submitted], natural_key=important_date_key)

        assert result.inserts == [submitted]
        assert result.deletions == [stored]
        assert result.updates == []

    def test_an_unknown_id_is_not_matched_on_its_natural_key(self) -> None:
        """A submission naming an id has said which row it is. A stale id is
        not the stored birthday under another name - it is an insert."""
        stored = _date(id=7, year=1990)
        stale = _date(id=999, year=1991)

        result = reconcile([stored], [stale], natural_key=important_date_key)

        assert result.inserts == [stale]
        assert result.deletions == [stored]
        assert result.updates == []

    def test_a_repeated_id_is_not_matched_to_another_row_on_its_natural_key(
        self,
    ) -> None:
        """The second submission naming row 1 cannot become an edit of row 2
        just because the two share a type."""
        first = _date(id=1, date_type=ImportantDateType.WORK_ANNIVERSARY, year=2011)
        second = _date(id=2, date_type=ImportantDateType.WORK_ANNIVERSARY, year=2015)
        claims_first = _date(
            id=1, date_type=ImportantDateType.WORK_ANNIVERSARY, year=2012
        )
        repeats_first = _date(
            id=1, date_type=ImportantDateType.WORK_ANNIVERSARY, year=2016
        )

        result = reconcile(
            [first, second],
            [claims_first, repeats_first],
            natural_key=important_date_key,
        )

        assert result.updates == [(first, claims_first)]
        assert result.inserts == [repeats_first]
        assert result.deletions == [second]

    def test_a_custom_date_type_keys_on_its_own_type(self) -> None:
        birthday = _date(id=1)
        anniversary = ImportantDate(
            contact_id=CONTACT_ID,
            date_type=ImportantDateType.CUSTOM,
            precision=DatePrecision.YEAR,
            year=2020,
            custom_date_type_id=3,
            id=2,
        )

        assert important_date_key(birthday) != important_date_key(anniversary)


class TestChangedFields:
    def test_reports_enums_by_value(self) -> None:
        """The payload is serialised to JSON in the outbox, so an enum has to
        cross as its value."""
        stored = _method("a@example.com", id=1)
        submitted = _method("+61412345678", id=1, method_type=MethodType.PHONE)

        assert diff_fields(stored, submitted, METHOD_FIELDS) == {
            "method_type": ("email", "phone"),
            "value": ("a@example.com", "+61412345678"),
        }

    def test_reports_transitions_to_and_from_none(self) -> None:
        stored = _method("a@example.com", id=1)
        submitted = _method("a@example.com", id=1, label="work")

        assert diff_fields(stored, submitted, METHOD_FIELDS) == {
            "label": (None, "work")
        }
        assert diff_fields(submitted, stored, METHOD_FIELDS) == {
            "label": ("work", None)
        }

    def test_identical_entities_report_nothing(self) -> None:
        stored = _address("1 Test St", id=1, label="home")
        submitted = _address("1 Test St", id=1, label="home")

        assert diff_fields(stored, submitted, ADDRESS_FIELDS) == {}

    def test_only_the_listed_fields_are_compared(self) -> None:
        """Ids and timestamps move on their own and are not a user's edit."""
        stored = _note("Same content", id=1)
        submitted = _note("Same content", id=2)

        assert diff_fields(stored, submitted, NOTE_FIELDS) == {}

    def test_important_date_fields_cover_every_editable_component(self) -> None:
        stored = _date(id=1, year=1990, month=3, day=9)
        submitted = _date(
            id=1, year=1991, month=None, day=None, precision=DatePrecision.YEAR
        )

        assert diff_fields(stored, submitted, IMPORTANT_DATE_FIELDS) == {
            "precision": ("full", "year"),
            "year": (1990, 1991),
            "month": (3, None),
            "day": (9, None),
        }


class TestPrefixedKeys:
    @pytest.mark.parametrize(
        ("prefix", "entity_type"),
        [
            (METHOD_PREFIX, "contact_method"),
            (ADDRESS_PREFIX, "contact_address"),
            (NOTE_PREFIX, "contact_note"),
        ],
    )
    def test_the_key_is_decoded_by_the_history_projection(
        self, prefix: str, entity_type: str
    ) -> None:
        """The one place the ``{prefix}_{id}_{field}`` format is written has to
        agree with the one place it is read."""
        keys = prefixed(prefix, 5, {"value": ("old", "new")})
        (key,) = keys

        match = _SUBENTITY_FIELD_RE.match(key)

        assert match is not None
        assert _SUBENTITY_PREFIX_ENTITY_TYPE[match.group(1)] == entity_type
        assert int(match.group(2)) == 5
        assert match.group(3) == "value"
        assert keys[key] == ("old", "new")

    def test_an_empty_diff_produces_no_keys(self) -> None:
        assert prefixed(METHOD_PREFIX, 5, {}) == {}

    def test_a_field_name_with_underscores_survives_the_round_trip(self) -> None:
        keys = prefixed(ADDRESS_PREFIX, 12, {"street_line_1": ("a", "b")})
        (key,) = keys

        match = _SUBENTITY_FIELD_RE.match(key)

        assert match is not None
        assert match.group(3) == "street_line_1"

    def test_an_important_date_edit_does_not_travel_as_a_prefixed_key(self) -> None:
        """Dates are published as ``ImportantDateUpdated`` instead, which is why
        the projection's prefix map has no entry for them."""
        assert _SUBENTITY_FIELD_RE.match("important_date_5_year") is None
        assert "important_date" not in _SUBENTITY_PREFIX_ENTITY_TYPE
