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

# JournalTag constants
MAX_TAG_NAME_LENGTH: int = 100
MAX_TAG_COLOR_LENGTH: int = 7  # Hex color format: #RRGGBB
