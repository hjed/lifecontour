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
