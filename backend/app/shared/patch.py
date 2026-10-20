"""Partial updates: the fields a caller names, applied to the row as it stands.

A caller that wants to change one field of an entity used to read the entity,
copy every other field from that read, and hand back the whole thing - and a
field somebody else changed between that read and the write went back to its
old value. A patch names only what the caller changes. The service applies it
to the entity as it reads it **under the row lock**, so nothing the caller did
not name can be overwritten, whatever happened in between.

``UNSET`` is "leave alone" and ``None`` is "clear": the two are different
values, and different types, so neither can stand in for the other.
"""

from dataclasses import dataclass, fields, replace
from enum import Enum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from _typeshed import DataclassInstance


class Unset(Enum):
    """The type of :data:`UNSET`."""

    UNSET = "UNSET"

    def __repr__(self) -> str:
        return "UNSET"


#: A patch field the caller did not name: the stored value stands.
UNSET: Final = Unset.UNSET


@dataclass(frozen=True, kw_only=True)
class FieldPatch:
    """Base for a patch of an entity's own fields.

    Subclasses declare fields named exactly as the entity's, typed
    ``T | Unset`` and defaulting to :data:`UNSET`. Only scalar fields belong
    here: changes to child collections are named by the domain's own patch,
    which knows how each one merges.
    """

    def changes(self) -> dict[str, object]:
        """The fields this patch sets, by name."""
        return {
            f.name: value
            for f in fields(self)
            if (value := getattr(self, f.name)) is not UNSET
        }

    def applied_to[T: DataclassInstance](self, target: T) -> T:
        """A copy of ``target`` with this patch's fields set; ``target`` is untouched.

        ``target`` must be a dataclass carrying every field the patch names.
        A copy rather than an in-place change, because the caller diffs the
        stored entity against the result.
        """
        return replace(target, **self.changes())

    def is_empty(self) -> bool:
        """Whether the patch names no field at all."""
        return not self.changes()
