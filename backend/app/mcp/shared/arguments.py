"""Tool argument types that keep their shape through fastmcp's validation.

fastmcp validates tool arguments with ``strict=False``, and pydantic lets a
runtime ``strict=False`` override field-level strictness — so ``StrictBool``
and the other ``Strict*`` types are silently relaxed on an MCP tool, and
``"true"`` arrives as ``True``. A ``BeforeValidator`` sees the raw argument
whatever the strict flag, so the types here refuse wrong-typed input on the
transport while still publishing the plain JSON-schema type.
"""

from typing import Annotated, Any

from pydantic import BeforeValidator

from app.shared.calendar_date import IsoCalendarDate


def _require_json_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("must be a JSON boolean (true or false)")
    return value


#: A boolean that only a JSON ``true`` or ``false`` satisfies.
#:
#: Use it for any confirmation an agent could plausibly send as ``"true"``,
#: ``"yes"`` or ``1`` — where coercing that into ``True`` would perform an
#: action nobody actually confirmed.
JsonBool = Annotated[bool, BeforeValidator(_require_json_bool)]


def _require_json_int(value: Any) -> int:
    # ``bool`` is a subclass of ``int`` in Python, so it is refused by name.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("must be a JSON integer")
    return value


#: Refuses anything but a JSON integer — not ``true``, ``"1"`` or ``1.0``, all of
#: which fastmcp's lax validation would otherwise turn into ``1``.
#:
#: Use it for an id or a position an agent sends: coercing ``true`` into ``1``
#: would act on record 1, or move something to index 1, when nobody named
#: either. It is a marker rather than a type alias so it can come **after** the
#: bounds — ``Annotated[int, Field(ge=0, le=INT32_MAX), JsonIntOnly]`` — because
#: pydantic publishes bounds placed after a before-validator as ``ge``/``le``
#: instead of JSON Schema's ``minimum``/``maximum``.
JsonIntOnly = BeforeValidator(_require_json_int)


#: A calendar day that only a ``"YYYY-MM-DD"`` string satisfies — never a number,
#: which fastmcp's lax validation would read as a timestamp, nor an instant. The
#: same type the REST schemas use, so both surfaces refuse the same input. For an
#: optional argument write ``JsonIsoDate | None``, so an explicit ``null`` is
#: accepted as absent rather than reaching the validator.
JsonIsoDate = IsoCalendarDate
