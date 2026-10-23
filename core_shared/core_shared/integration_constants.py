"""Shared constants for integration infrastructure."""

from uuid import NAMESPACE_URL, uuid5

GOOGLE_ARQ_QUEUE_NAME = "google"
STRAVA_ARQ_QUEUE_NAME = "strava"
SNIPEIT_ARQ_QUEUE_NAME = "arq:snipeit"
IMMICH_ARQ_QUEUE_NAME = "arq:immich"


def snipeit_maintenance_calendar_id(user_id: str) -> str:
    """The synthetic calendar ``user_id``'s Snipe-IT maintenances are imported into.

    Snipe-IT ids are per instance, so two users' instances hand out the same
    maintenance id. An import is linked on this calendar by its
    ``snipeit_maint:{id}``, and a link is unique per calendar, so each user has
    their own: one shared calendar let another user's import stand in for this
    user's record.
    """
    return str(uuid5(NAMESPACE_URL, f"snipeit:maintenance:{user_id}"))
