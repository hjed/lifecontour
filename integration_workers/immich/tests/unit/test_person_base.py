"""Unit tests for the Immich person's synced base (#1900).

The push merges ``name`` and ``birthDate`` three ways against what the last
sync agreed on, so an edit made in Immich since is kept rather than
overwritten.
"""

from __future__ import annotations

from immich_models import ImmichPerson
from person_base import (
    birth_date_keys,
    name_keys,
    person_entries,
    plan_push,
    resolve_base,
)


def _person(name: str = "Ada Lovelace", birth_date: str | None = None) -> ImmichPerson:
    return ImmichPerson(id="person-1", name=name, birth_date=birth_date)


class TestKeys:
    def test_name_key_ignores_whitespace(self) -> None:
        assert name_keys(" Ada   Lovelace ") == name_keys("Ada Lovelace")

    def test_name_key_keeps_case(self) -> None:
        assert name_keys("ada lovelace") != name_keys("Ada Lovelace")

    def test_blank_name_has_no_key(self) -> None:
        assert name_keys("  ") == frozenset()
        assert name_keys(None) == frozenset()

    def test_birth_date_key_reads_the_date(self) -> None:
        assert len(birth_date_keys("1815-12-10")) == 1
        assert birth_date_keys("1815-12-10") != birth_date_keys("1815-12-11")

    def test_unreadable_birth_date_differs_from_every_readable_one(self) -> None:
        assert birth_date_keys("10/12/1815") != birth_date_keys("1815-12-10")
        assert len(birth_date_keys("10/12/1815")) == 1

    def test_no_birth_date_has_no_key(self) -> None:
        assert birth_date_keys(None) == frozenset()


class TestResolveBase:
    def test_recorded_base_wins(self) -> None:
        recorded = {"name": name_keys("Ada King")}

        assert (
            resolve_base(
                recorded, _person(), recorded_version="v1", current_version="v2"
            )
            == recorded
        )

    def test_unchanged_person_is_its_own_base(self) -> None:
        person = _person(birth_date="1815-12-10")

        assert resolve_base(
            None, person, recorded_version="v1", current_version="v1"
        ) == person_entries(person)

    def test_changed_person_without_a_base_gets_an_empty_one(self) -> None:
        assert (
            resolve_base(None, _person(), recorded_version="v1", current_version="v2")
            == {}
        )


class TestPlanPush:
    """``plan_push`` decides what to send; ``settle`` reads what Immich kept."""

    def test_immich_name_edit_is_kept(self) -> None:
        base = {"name": name_keys("Ada Lovelace"), "birthDate": frozenset()}
        current = _person(name="Ada King")

        plan = plan_push(
            local_name="Ada Lovelace",
            local_birth_date=None,
            current=current,
            base=base,
        )
        outcome = plan.settle(current)

        assert "name" not in plan.update_data
        assert outcome.pending_import is False
        assert outcome.base["name"] == name_keys("Ada Lovelace")

    def test_immich_birthday_edit_is_kept_and_left_for_the_pull(self) -> None:
        base = {
            "name": name_keys("Ada Lovelace"),
            "birthDate": birth_date_keys("1815-12-10"),
        }
        current = _person(birth_date="1815-12-11")

        plan = plan_push(
            local_name="Ada Lovelace",
            local_birth_date="1815-12-10",
            current=current,
            base=base,
        )
        outcome = plan.settle(current)

        assert "birthDate" not in plan.update_data
        assert outcome.pending_import is True
        assert outcome.base["birthDate"] == birth_date_keys("1815-12-10")

    def test_local_edits_are_pushed(self) -> None:
        base = {
            "name": name_keys("Ada Lovelace"),
            "birthDate": birth_date_keys("1815-12-10"),
        }
        response = _person(name="Ada King", birth_date="1815-12-11")

        plan = plan_push(
            local_name="Ada King",
            local_birth_date="1815-12-11",
            current=_person(birth_date="1815-12-10"),
            base=base,
        )
        outcome = plan.settle(response)

        assert plan.update_data == {"name": "Ada King", "birthDate": "1815-12-11"}
        assert outcome.pending_import is False
        assert outcome.base == person_entries(response)

    def test_both_sides_changed_local_wins_with_the_base_from_the_response(
        self,
    ) -> None:
        base = {
            "name": name_keys("Ada Lovelace"),
            "birthDate": birth_date_keys("1815-12-10"),
        }
        response = _person(name="Countess Ada", birth_date="1815-12-12")

        plan = plan_push(
            local_name="Countess Ada",
            local_birth_date="1815-12-12",
            current=_person(name="Ada King", birth_date="1815-12-11"),
            base=base,
        )
        outcome = plan.settle(response)

        assert plan.update_data == {"name": "Countess Ada", "birthDate": "1815-12-12"}
        assert outcome.pending_import is False
        assert outcome.base == person_entries(response)

    def test_immich_birthday_change_without_a_local_one_is_left_for_the_pull(
        self,
    ) -> None:
        base = {"name": name_keys("Ada Lovelace"), "birthDate": frozenset()}
        current = _person(birth_date="1815-12-10")

        plan = plan_push(
            local_name="Ada Lovelace",
            local_birth_date=None,
            current=current,
            base=base,
        )
        outcome = plan.settle(current)

        assert "birthDate" not in plan.update_data
        assert outcome.pending_import is True
        assert outcome.base["birthDate"] == frozenset()

    def test_agreed_birthday_without_a_local_one_is_not_flagged(self) -> None:
        base = {"birthDate": birth_date_keys("1815-12-10")}
        current = _person(birth_date="1815-12-10")

        plan = plan_push(
            local_name="Ada Lovelace",
            local_birth_date=None,
            current=current,
            base=base,
        )

        assert plan.settle(current).pending_import is False

    def test_second_push_before_the_pull_still_holds_back(self) -> None:
        base = {"birthDate": birth_date_keys("1815-12-10")}
        current = _person(birth_date="1815-12-11")
        first = plan_push(
            local_name="Ada Lovelace",
            local_birth_date="1815-12-10",
            current=current,
            base=base,
        )

        second = plan_push(
            local_name="Ada Lovelace",
            local_birth_date="1815-12-10",
            current=current,
            base=first.settle(current).base,
        )

        assert "birthDate" not in second.update_data
        assert second.settle(current).pending_import is True

    def test_nothing_to_send_when_both_sides_agree(self) -> None:
        current = _person(birth_date="1815-12-10")

        plan = plan_push(
            local_name="Ada Lovelace",
            local_birth_date="1815-12-10",
            current=current,
            base=person_entries(current),
        )
        outcome = plan.settle(current)

        assert plan.update_data == {}
        assert outcome.pending_import is False
        assert outcome.base == person_entries(current)

    def test_birthday_changed_in_immich_during_the_push_is_left_for_the_pull(
        self,
    ) -> None:
        """The birthday agreed at the GET, but the PUT's response holds a new one."""
        base = {
            "name": name_keys("Ada Lovelace"),
            "birthDate": birth_date_keys("1815-12-10"),
        }
        response = _person(name="Ada King", birth_date="1815-12-11")

        plan = plan_push(
            local_name="Ada King",
            local_birth_date="1815-12-10",
            current=_person(birth_date="1815-12-10"),
            base=base,
        )
        outcome = plan.settle(response)

        assert plan.update_data == {"name": "Ada King"}
        assert outcome.pending_import is True
        assert outcome.base == {
            "name": name_keys("Ada King"),
            "birthDate": birth_date_keys("1815-12-10"),
        }

    def test_name_changed_in_immich_during_the_push_keeps_its_base(self) -> None:
        base = {"name": name_keys("Ada Lovelace"), "birthDate": frozenset()}
        response = _person(name="Ada King", birth_date="1815-12-10")

        plan = plan_push(
            local_name="Ada Lovelace",
            local_birth_date="1815-12-10",
            current=_person(),
            base=base,
        )
        outcome = plan.settle(response)

        assert plan.update_data == {"birthDate": "1815-12-10"}
        assert outcome.base["name"] == name_keys("Ada Lovelace")

    def test_birthday_only_base_lets_a_local_name_overwrite_an_immich_rename(
        self,
    ) -> None:
        # A link from before bases recorded no name: its first pull records a
        # birthday-only base, so an Immich rename before the first push is a
        # conflict, which local wins (a documented limit).
        plan = plan_push(
            local_name="Ada Lovelace",
            local_birth_date=None,
            current=_person(name="Ada King"),
            base={"birthDate": frozenset()},
        )

        assert plan.update_data == {"name": "Ada Lovelace"}
