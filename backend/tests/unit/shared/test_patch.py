"""Unit tests for ``FieldPatch``: what a caller names, and nothing else."""

from dataclasses import dataclass

from app.shared.patch import UNSET, FieldPatch, Unset


@dataclass
class Person:
    name: str
    nickname: str | None = None
    age: int | None = None


@dataclass(frozen=True, kw_only=True)
class PersonPatch(FieldPatch):
    name: str | Unset = UNSET
    nickname: str | None | Unset = UNSET
    age: int | None | Unset = UNSET


STORED = Person(name="Ada", nickname="Countess", age=36)


def test_unset_fields_keep_the_stored_value() -> None:
    assert PersonPatch(name="Augusta").applied_to(STORED) == Person(
        name="Augusta", nickname="Countess", age=36
    )


def test_none_clears_a_field() -> None:
    assert PersonPatch(nickname=None).applied_to(STORED) == Person(
        name="Ada", nickname=None, age=36
    )


def test_applying_leaves_the_target_untouched() -> None:
    target = Person(name="Ada", nickname="Countess")

    PersonPatch(name="Augusta").applied_to(target)

    assert target == Person(name="Ada", nickname="Countess")


def test_changes_names_only_what_was_set() -> None:
    assert PersonPatch(nickname=None, age=37).changes() == {
        "nickname": None,
        "age": 37,
    }


def test_an_empty_patch_changes_nothing() -> None:
    assert PersonPatch().is_empty()
    assert PersonPatch().applied_to(STORED) == STORED
    assert not PersonPatch(nickname=None).is_empty()
