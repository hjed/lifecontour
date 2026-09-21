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
    IMPORTANT_DATES,
    METHOD_FIELDS,
    METHOD_PREFIX,
    METHODS,
    NOTE_FIELDS,
    NOTE_PREFIX,
    NOTES,
    aggregate_change,
    diff_fields,
    important_date_key,
    important_date_unique_claims,
    method_unique_claims,
    prefixed,
    reconcile,
    render_important_date,
    render_note,
    with_primary_method,
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

    def test_updates_keep_submission_order_across_both_passes(self) -> None:
        """Ids are matched in an earlier pass than natural keys, but the pairs
        come back in the order they were submitted."""
        stored_birthday = _date(id=1)
        stored_anniversary = _date(
            id=2, date_type=ImportantDateType.WORK_ANNIVERSARY, year=2015
        )
        by_key = _date(year=1991)
        by_id = _date(id=2, date_type=ImportantDateType.WORK_ANNIVERSARY, year=2016)

        result = reconcile(
            [stored_birthday, stored_anniversary],
            [by_key, by_id],
            natural_key=important_date_key,
        )

        assert result.updates == [
            (stored_birthday, by_key),
            (stored_anniversary, by_id),
        ]

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


class TestAggregateRendering:
    """The aggregate row describes a list's membership, not how long it is."""

    def test_a_full_date_renders_its_type_and_day(self) -> None:
        assert render_important_date(_date()) == "birthday:1990-03-09"

    def test_a_day_month_date_renders_without_a_year(self) -> None:
        date = _date(year=None, precision=DatePrecision.DAY_MONTH)

        assert render_important_date(date) == "birthday:--03-09"

    def test_a_year_only_date_renders_its_year(self) -> None:
        date = _date(
            date_type=ImportantDateType.WORK_ANNIVERSARY,
            precision=DatePrecision.YEAR,
            month=None,
            day=None,
            year=2015,
        )

        assert render_important_date(date) == "work_anniversary:2015"

    def test_a_custom_date_renders_its_own_type_name(self) -> None:
        date = ImportantDate(
            contact_id=CONTACT_ID,
            date_type=ImportantDateType.CUSTOM,
            precision=DatePrecision.YEAR,
            year=2020,
            custom_date_type_id=3,
            custom_date_type_name="Graduation",
        )

        assert render_important_date(date) == "custom(Graduation):2020"

    def test_a_long_note_is_truncated(self) -> None:
        """The note-added event carries 100 characters; the row does too."""
        rendered = render_note(_note("x" * 150))

        assert rendered == "x" * 100 + "…"

    def test_a_membership_change_reports_both_lists_sorted(self) -> None:
        before = [_method("b@example.com"), _method("a@example.com")]
        after = [_method("a@example.com")]

        assert aggregate_change(METHODS, before, after) == {
            "contact_methods": (
                "email:a@example.com, email:b@example.com",
                "email:a@example.com",
            )
        }

    def test_an_emptied_list_reports_none(self) -> None:
        assert aggregate_change(NOTES, [_note("Only note")], []) == {
            "notes": ("Only note", "None")
        }

    def test_lists_that_read_the_same_report_nothing(self) -> None:
        """A note deleted and re-created with the same words has changed ids,
        and nothing a reader of the feed could see."""
        assert (
            aggregate_change(NOTES, [_note("Same", id=1)], [_note("Same", id=2)]) == {}
        )

    def test_important_dates_report_under_their_own_key(self) -> None:
        change = aggregate_change(IMPORTANT_DATES, [], [_date()])

        assert change == {"important_dates": ("None", "birthday:1990-03-09")}


class TestReconcileAroundUniqueKeys:
    """Postgres checks a non-deferrable unique index row by row, so matched
    updates are ordered: a row lets go of a unique value before another row
    takes it."""

    def test_the_old_primary_is_demoted_before_the_new_one_is_promoted(self) -> None:
        old_primary = _method("a@example.com", id=1, is_primary=True)
        other = _method("b@example.com", id=2)
        promote = _method("b@example.com", id=2, is_primary=True)
        demote = _method("a@example.com", id=1)

        result = reconcile(
            [old_primary, other], [promote, demote], unique_claims=method_unique_claims
        )

        assert result.updates == [(old_primary, demote), (other, promote)]

    def test_the_old_birthday_is_retyped_before_the_new_one(self) -> None:
        birthday = _date(id=1)
        anniversary = _date(id=2, date_type=ImportantDateType.WORK_ANNIVERSARY)
        becomes_birthday = _date(id=2)
        becomes_anniversary = _date(id=1, date_type=ImportantDateType.WORK_ANNIVERSARY)

        result = reconcile(
            [birthday, anniversary],
            [becomes_birthday, becomes_anniversary],
            unique_claims=important_date_unique_claims,
        )

        assert result.updates == [
            (birthday, becomes_anniversary),
            (anniversary, becomes_birthday),
        ]

    def test_an_email_moves_to_another_row_after_it_is_released(self) -> None:
        """A chain rather than a cycle: one order always works."""
        first = _method("a@example.com", id=1)
        second = _method("b@example.com", id=2)
        takes_a = _method("a@example.com", id=2)
        moves_on = _method("c@example.com", id=1)

        result = reconcile(
            [first, second], [takes_a, moves_on], unique_claims=method_unique_claims
        )

        assert result.updates == [(first, moves_on), (second, takes_a)]

    def test_an_email_is_compared_as_the_index_normalises_it(self) -> None:
        """The index is on LOWER(BTRIM(value)), so a change of case is the
        same value."""
        first = _method("A@Example.COM", id=1)
        second = _method("b@example.com", id=2)
        takes_a = _method("a@example.com", id=2)
        moves_on = _method("c@example.com", id=1)

        result = reconcile(
            [first, second], [takes_a, moves_on], unique_claims=method_unique_claims
        )

        assert result.updates == [(first, moves_on), (second, takes_a)]

    def test_a_swap_is_broken_by_re_creating_one_side(self) -> None:
        """No order of two in-place updates swaps two unique values. The first
        row is re-created instead - deleted before the updates, inserted after -
        and keeps its pairing, because it is still an edit the feed reports."""
        first = _method("a@example.com", id=1)
        second = _method("b@example.com", id=2)
        first_takes_b = _method("b@example.com", id=1)
        second_takes_a = _method("a@example.com", id=2)

        result = reconcile(
            [first, second],
            [first_takes_b, second_takes_a],
            unique_claims=method_unique_claims,
        )

        assert result.updates == [(second, second_takes_a)]
        assert result.recreated == [(first, first_takes_b)]
        assert result.deletions == []
        assert result.inserts == []

    def test_updates_that_share_no_unique_value_keep_their_order(self) -> None:
        first = _method("a@example.com", id=1)
        second = _method("b@example.com", id=2)
        edit_second = _method("b@example.com", id=2, label="work")
        edit_first = _method("a@example.com", id=1, label="home")

        result = reconcile(
            [first, second],
            [edit_second, edit_first],
            unique_claims=method_unique_claims,
        )

        assert result.updates == [(second, edit_second), (first, edit_first)]


class TestWithPrimaryMethod:
    """Setting a contact's primary email or phone without touching the rest."""

    def test_edits_the_stored_primary_in_place(self) -> None:
        primary = _method("old@example.com", id=1, is_primary=True)
        other = _method("work@example.com", id=2)
        phone = _method("+61412345678", id=3, method_type=MethodType.PHONE)

        result = with_primary_method(
            [primary, other, phone], MethodType.EMAIL, "new@example.com", CONTACT_ID
        )

        assert [(m.id, m.value, m.is_primary) for m in result] == [
            (1, "new@example.com", True),
            (2, "work@example.com", False),
            (3, "+61412345678", False),
        ]

    def test_promotes_the_first_of_the_type_when_none_is_primary(self) -> None:
        first = _method("first@example.com", id=1)
        second = _method("second@example.com", id=2)

        result = with_primary_method(
            [first, second], MethodType.EMAIL, "new@example.com", CONTACT_ID
        )

        assert [(m.id, m.value, m.is_primary) for m in result] == [
            (1, "new@example.com", True),
            (2, "second@example.com", False),
        ]

    def test_adds_a_primary_when_the_contact_has_none_of_the_type(self) -> None:
        email = _method("a@example.com", id=1, is_primary=True)

        result = with_primary_method(
            [email], MethodType.PHONE, "+61412345678", CONTACT_ID
        )

        assert result[0] is email
        added = result[1]
        assert (added.id, added.method_type, added.value, added.is_primary) == (
            None,
            MethodType.PHONE,
            "+61412345678",
            True,
        )

    def test_leaves_the_stored_objects_unchanged(self) -> None:
        """The stored list is the before-image the reconcile diffs against."""
        primary = _method("old@example.com", id=1, is_primary=True)

        with_primary_method([primary], MethodType.EMAIL, "new@example.com", CONTACT_ID)

        assert primary.value == "old@example.com"
