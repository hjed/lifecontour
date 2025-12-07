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
