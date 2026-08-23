"""Constants for the journal domain."""

from enum import StrEnum

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
class TrackGrade(StrEnum):
    """Australian Walking Track Grading System grades (BUSHWALKING)."""

    GRADE_1 = "Grade 1"
    GRADE_2 = "Grade 2"
    GRADE_3 = "Grade 3"
    GRADE_4 = "Grade 4"
    GRADE_5 = "Grade 5"


VALID_TRACK_GRADES: list[str] = [member.value for member in TrackGrade]

# CanyoningData constants (CANYONING type)
# French canyon grading format: v[vertical]a[aquatic][engagement][stars]
# Example: v3a2IV** = vertical 3, aquatic 2, engagement IV, 2 stars
# Vertical: 1-7, Aquatic: 1-7, Engagement: I-VI (optional), Stars: *-*** (optional)
FRENCH_CANYON_GRADE_PATTERN: str = r"^v[1-7]a[1-7](I{1,3}|IV|V|VI)?(\*{1,3})?$"


# ClimbingData constants (CLIMBING type)
# These are mutually-exclusive climbing disciplines/styles. "indoor" is NOT a
# type — it is a separate boolean flag on ClimbingData, since a climb can be
# indoor in any of these styles.
class ClimbingType(StrEnum):
    """Climbing disciplines (CLIMBING); 'indoor' is a separate flag."""

    SPORT = "sport"
    TRAD = "trad"
    BOULDERING = "bouldering"
    TOP_ROPE = "top_rope"


VALID_CLIMBING_TYPES: list[str] = [member.value for member in ClimbingType]


# AbseilPitch constants (abseil_pitches table)
class AnchorLocation(StrEnum):
    """Where a pitch anchor sits (abseil_pitches)."""

    TR = "TR"
    TL = "TL"
    CENTRE = "Centre"


VALID_ANCHOR_LOCATIONS: list[str] = [member.value for member in AnchorLocation]


class AnchorType(StrEnum):
    """Pitch anchor types (abseil_pitches)."""

    CHAINS = "chains"
    DOUBLE_BOLT = "double bolt"
    SINGLE_BOLT = "single bolt"
    SLING_ON_TREE = "sling on tree"
    SLING_ON_LOG = "sling on log"
    SLING_ON_BOULDER = "sling on boulder"
    SLING_ON_BOLLARD = "sling on bollard"
    ARTIFICIAL_REMOVABLE = "artificial removable"


VALID_ANCHOR_TYPES: list[str] = [member.value for member in AnchorType]

# How a pitch is descended. A null pitch_type is treated as "abseil" for
# backward compatibility with rows created before the column existed.
PITCH_TYPE_ABSEIL: str = "abseil"


class PitchType(StrEnum):
    """How a pitch is descended; null is treated as abseil."""

    ABSEIL = PITCH_TYPE_ABSEIL
    JUMP = "jump"
    DOWN_CLIMB = "down_climb"


VALID_PITCH_TYPES: list[str] = [member.value for member in PitchType]


# ActivityTemplate constants (activity_templates table)
class TemplateType(StrEnum):
    """Activity template types (activity_templates)."""

    ABSEILING = "abseiling"
    CANYONING = "canyoning"
    CAVING = "caving"
    CLIMBING = "climbing"


VALID_TEMPLATE_TYPES: list[str] = [member.value for member in TemplateType]


class CanyonType(StrEnum):
    """Canyon character recorded on a template."""

    VERTICAL = "vertical"
    AQUATIC = "aquatic"
    MIXED = "mixed"


VALID_CANYON_TYPES: list[str] = [member.value for member in CanyonType]

MAX_TEMPLATE_NAME_LENGTH: int = 200
MAX_REGION_LENGTH: int = 200
MAX_WATER_GAUGE_NAME_LENGTH: int = 200


# KayakingData constants (KAYAKING type)
# International Scale of River Difficulty — Grade I (easiest) to VI (hardest)
class RapidsGrade(StrEnum):
    """International Scale of River Difficulty (KAYAKING)."""

    GRADE_I = "I"
    GRADE_II = "II"
    GRADE_III = "III"
    GRADE_IV = "IV"
    GRADE_V = "V"
    GRADE_VI = "VI"


VALID_RAPIDS_GRADES: list[str] = [member.value for member in RapidsGrade]

# GearItem constants (gear_items table)
MAX_GEAR_ITEM_NAME_LENGTH: int = 200
MAX_GEAR_ITEM_FIELD_LENGTH: int = 200  # model, serial_number, manufacturer


# GearMaintenanceData constants (GEAR_MAINTENANCE type)
class MaintenanceType(StrEnum):
    """Kinds of gear maintenance (GEAR_MAINTENANCE)."""

    RETIRING_GEAR = "retiring gear"
    REPAIRING_GEAR = "repairing gear"
    ROUTINE_INSPECTION = "routine inspection"
    ROUTINE_MAINTENANCE = "routine maintenance"


VALID_MAINTENANCE_TYPES: list[str] = [member.value for member in MaintenanceType]
MAX_MAINTENANCE_TYPE_LENGTH: int = 100
MAX_RETIREMENT_REASON_LENGTH: int = 500
