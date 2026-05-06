from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class StravaAthleteMapping:
    """Mapping between a Strava athlete and a system Contact.

    Used to explicitly map an imported Strava activity's athlete (or
    group participants) to a Contact entity, overriding automated name matching.
    """

    user_id: str
    strava_athlete_id: str
    strava_athlete_name: str
    contact_id: int
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
