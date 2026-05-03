"""Constants for the journal domain."""

# Maximum depth of journal hierarchy (parent-child relationships)
# Value: 5 levels as per journal-system-specification.md
MAX_HIERARCHY_DEPTH: int = 5

# Maximum length of journal title
# Value: 500 characters as per journal-system-specification.md
MAX_TITLE_LENGTH: int = 500

# Maximum length of user_id field
# Matches existing patterns in user_google_auth table
MAX_USER_ID_LENGTH: int = 50

# Calendar constants
MAX_CALENDAR_NAME_LENGTH: int = 100
MAX_CALENDAR_COLOR_LENGTH: int = 7  # Hex color format: #RRGGBB
MAX_GOOGLE_CALENDAR_ID_LENGTH: int = 255

# CalendarInfo constants (EVENT type)
MAX_LOCATION_LENGTH: int = 500
MAX_TIMEZONE_LENGTH: int = 50

# MoodData constants (MOOD_RATING type)
MIN_MOOD_VALUE: int = 1
MAX_MOOD_VALUE: int = 10
MIN_ENERGY_LEVEL: int = 1
MAX_ENERGY_LEVEL: int = 10
MAX_MOOD_LABEL_LENGTH: int = 100

# PhotoAlbumData constants (PHOTO_ALBUM type)
MAX_IMMICH_ALBUM_ID_LENGTH: int = 255

# PlanData constants (PLAN type)
MAX_PLAN_DOCUMENT_URL_LENGTH: int = 2000
MAX_PLAN_DOCUMENT_TITLE_LENGTH: int = 500

# TravelData constants (TRAVEL type)
MAX_FLIGHT_NUMBER_LENGTH: int = 20
MAX_AIRLINE_LENGTH: int = 100
MAX_AIRPORT_CODE_LENGTH: int = 10
MAX_BOOKING_REFERENCE_LENGTH: int = 100
MAX_SEAT_NUMBER_LENGTH: int = 20
MAX_CONFIRMATION_NUMBER_LENGTH: int = 100
MAX_ACCOMMODATION_NAME_LENGTH: int = 200
MAX_TRANSPORTATION_TYPE_LENGTH: int = 50

# FitnessData constants (FITNESS type)
MAX_STRAVA_ACTIVITY_ID_LENGTH: int = 255

# OutdoorActivityData constants (OUTDOOR_ACTIVITY type)
MAX_WEATHER_CONDITIONS_LENGTH: int = 200
MAX_ROLE_LENGTH: int = 100
MAX_PARTICIPANT_NOTES_LENGTH: int = 2000

# BushwalkingData constants (BUSHWALKING type)
VALID_TRACK_GRADES: list[str] = [
    "Grade 1",
    "Grade 2",
    "Grade 3",
    "Grade 4",
    "Grade 5",
]

# CanyoningData constants (CANYONING type)
# French canyon grading format: v[vertical]a[aquatic][engagement][stars]
# Example: v3a2IV** = vertical 3, aquatic 2, engagement IV, 2 stars
# Vertical: 1-7, Aquatic: 1-7, Engagement: I-VI (optional), Stars: *-*** (optional)
FRENCH_CANYON_GRADE_PATTERN: str = r"^v[1-7]a[1-7](I{1,3}|IV|V|VI)?(\*{1,3})?$"

# ClimbingData constants (CLIMBING type)
VALID_CLIMBING_TYPES: list[str] = [
    "sport",
    "trad",
    "bouldering",
]

# AbseilPitch constants (abseil_pitches table)
VALID_ANCHOR_LOCATIONS: list[str] = [
    "TR",
    "TL",
    "Centre",
]

VALID_ANCHOR_TYPES: list[str] = [
    "chains",
    "double bolt",
    "single bolt",
    "sling on tree",
    "sling on log",
    "sling on boulder",
    "sling on bollard",
    "artificial removable",
]

# ActivityTemplate constants (activity_templates table)
VALID_TEMPLATE_TYPES: list[str] = [
    "canyoning",
    "caving",
    "climbing",
]

VALID_CANYON_TYPES: list[str] = [
    "vertical",
    "aquatic",
    "mixed",
]

MAX_TEMPLATE_NAME_LENGTH: int = 200
MAX_REGION_LENGTH: int = 200
MAX_WATER_GAUGE_NAME_LENGTH: int = 200

# KayakingData constants (KAYAKING type)
# International Scale of River Difficulty — Grade I (easiest) to VI (hardest)
VALID_RAPIDS_GRADES: list[str] = ["I", "II", "III", "IV", "V", "VI"]

# GearItem constants (gear_items table)
MAX_GEAR_ITEM_NAME_LENGTH: int = 200
MAX_GEAR_ITEM_FIELD_LENGTH: int = 200  # model, serial_number, manufacturer
