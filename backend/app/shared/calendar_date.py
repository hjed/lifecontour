"""A calendar day sent as an ISO ``YYYY-MM-DD`` string, and nothing else.

Shared by REST and MCP so both surfaces accept and refuse exactly the same due
dates. Pydantic's lax date parsing would read a JSON number as a Unix timestamp
and an instant string as its date — a day nobody named, and one day off for half
the world — so the raw value is checked before pydantic sees it. A
``BeforeValidator`` runs whatever the strict flag, which matters on MCP, where
fastmcp validates tool arguments with ``strict=False``.
"""

import datetime
import re
from typing import Annotated, Any

from pydantic import BeforeValidator

_ISO_CALENDAR_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _require_iso_calendar_date(value: Any) -> datetime.date:
    if not isinstance(value, str) or _ISO_CALENDAR_DATE.fullmatch(value) is None:
        raise ValueError("must be a calendar date as a YYYY-MM-DD string")
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{value} is not a real calendar date") from error


#: A day such as ``"2026-11-30"``: no number, no time, no other format. Published
#: in the JSON schema as ``{"type": "string", "format": "date"}``.
IsoCalendarDate = Annotated[datetime.date, BeforeValidator(_require_iso_calendar_date)]
