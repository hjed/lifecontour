"""Shared constants for integration infrastructure."""

from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5

GOOGLE_ARQ_QUEUE_NAME = "google"
STRAVA_ARQ_QUEUE_NAME = "strava"
SNIPEIT_ARQ_QUEUE_NAME = "arq:snipeit"
IMMICH_ARQ_QUEUE_NAME = "arq:immich"


class SyntheticCalendar(StrEnum):
    """An integration whose records are linked on a calendar it makes up.

    Strava and Snipe-IT have no calendars of their own, but a journal sync event
    names one. Each value is the namespace that calendar's id is derived from;
    it is not the event's ``integration_source``, and changing one re-homes
    every user's links, so a value only ever gets added.
    """

    STRAVA = "strava"
    SNIPEIT_MAINTENANCE = "snipeit:maintenance"


def synthetic_calendar_id(calendar: SyntheticCalendar, user_id: str) -> str:
    """The synthetic calendar ``user_id``'s records of ``calendar`` are linked on.

    A link is unique per calendar, and the backend creates a calendar the first
    time an event names it, owned by that event's user. One calendar shared by
    every user is therefore owned by whoever synced first, hidden from everyone
    else, and lets one user's link stand in for another's record wherever ids
    are not globally unique (#1510, #1856). Each user has their own.
    """
    return str(uuid5(NAMESPACE_URL, f"{calendar}:{user_id}"))
