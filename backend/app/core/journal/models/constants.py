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
