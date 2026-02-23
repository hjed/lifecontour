"""Journal type definitions for the journal domain.

The journal type system allows journals to have multiple types, each adding
specific fields and functionality. Types are detected by the presence of
corresponding data tables.

Type System Architecture:
- Each type has a corresponding `journal_{type}_data` table
- A journal has a type if a row exists in that type's data table
- NOTE type is special - it uses only base journal fields (no additional table)
- Type-specific data tables contain required and optional fields
"""

from enum import StrEnum


class JournalType(StrEnum):
    """
    Enumeration of journal types.

    Base Types (Iteration 4):
    - NOTE: Simple text notes using only base journal fields
    - EVENT: Calendar events with time and location information
    - MOOD_RATING: Mood and energy level tracking
    - PLAN: Event planning with document links
    - TRAVEL: Travel itineraries with flights, accommodations, transportation
    - PHOTO_ALBUM: Links to Immich photo albums

    Additional types will be added in future iterations:
    - FITNESS: Base type for fitness activities
    - OUTDOOR_ACTIVITY: Extends FITNESS
    - BUSHWALKING, CANYONING, etc.: Specialized activity types
    """

    # Base types (Iteration 4 - Part 1)
    NOTE = "note"
    EVENT = "event"
    MOOD_RATING = "mood_rating"

    # Base types (Iteration 4 - Part 2)
    PLAN = "plan"
    TRAVEL = "travel"
    PHOTO_ALBUM = "photo_album"

    # Activity types (Iteration 4.5)
    FITNESS = "fitness"
    OUTDOOR_ACTIVITY = "outdoor_activity"  # Iteration 4.5-003
    BUSHWALKING = "bushwalking"  # Iteration 4.5-003
    JOGGING = "jogging"  # Iteration 4.5-003
    ABSEILING_TRIP = "abseiling_trip"  # Iteration 4.5-004
    CANYONING = "canyoning"  # Iteration 4.5-004
    CLIMBING = "climbing"  # Iteration 4.5-004
    # KAYAKING = "kayaking"  # Future: Iteration 4.5-005
    # CROSS_COUNTRY_SKIING = "cross_country_skiing"  # Future: Iteration 4.5-005

    def __str__(self) -> str:
        """Return string representation of the type."""
        return self.value

    @classmethod
    def requires_data_table(cls, journal_type: "JournalType") -> bool:
        """
        Check if a journal type requires a separate data table.

        NOTE type is special - it uses only base journal fields and
        doesn't have a separate data table.

        Args:
            journal_type: The journal type to check

        Returns:
            True if the type requires a data table, False otherwise
        """
        return journal_type != cls.NOTE

    @classmethod
    def get_dependencies(cls, journal_type: "JournalType") -> list["JournalType"]:
        """
        Get the list of types that must be added when this type is added.

        Type dependencies are transitive and automatically added by the service layer.
        For example, adding CANYONING automatically adds BUSHWALKING, ABSEILING_TRIP,
        OUTDOOR_ACTIVITY, and FITNESS.

        Current implementation (Iteration 4):
        - Base types (NOTE, EVENT, MOOD_RATING, PLAN, TRAVEL, PHOTO_ALBUM) have no dependencies

        Future implementation (Iteration 4.5):
        - FITNESS: No dependencies (base fitness type)
        - OUTDOOR_ACTIVITY: Requires FITNESS
        - BUSHWALKING: Requires OUTDOOR_ACTIVITY, FITNESS
        - ABSEILING_TRIP: Requires OUTDOOR_ACTIVITY, FITNESS
        - CANYONING: Requires BUSHWALKING, ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS
        - CLIMBING: Requires OUTDOOR_ACTIVITY, FITNESS
        - KAYAKING: Requires OUTDOOR_ACTIVITY, FITNESS
        - CROSS_COUNTRY_SKIING: Requires BUSHWALKING, OUTDOOR_ACTIVITY, FITNESS
        - JOGGING: Requires FITNESS

        Args:
            journal_type: The journal type to get dependencies for

        Returns:
            List of journal types that must be added (empty for base types)
        """
        # Type dependency mapping
        dependencies: dict[JournalType, list[JournalType]] = {
            # Base types have no dependencies
            cls.NOTE: [],
            cls.EVENT: [],
            cls.MOOD_RATING: [],
            cls.PLAN: [],
            cls.TRAVEL: [],
            cls.PHOTO_ALBUM: [],
            # Fitness types (Iteration 4.5-002/003)
            cls.FITNESS: [],  # Base fitness type - no dependencies
            cls.OUTDOOR_ACTIVITY: [cls.FITNESS],
            cls.BUSHWALKING: [cls.OUTDOOR_ACTIVITY, cls.FITNESS],
            cls.JOGGING: [cls.FITNESS],  # NOT OUTDOOR_ACTIVITY - jogging can be indoors
            # Activity types (Iteration 4.5-004)
            cls.ABSEILING_TRIP: [cls.OUTDOOR_ACTIVITY, cls.FITNESS],
            cls.CANYONING: [
                cls.BUSHWALKING,
                cls.ABSEILING_TRIP,
                cls.OUTDOOR_ACTIVITY,
                cls.FITNESS,
            ],
            cls.CLIMBING: [cls.OUTDOOR_ACTIVITY, cls.FITNESS],
            # cls.KAYAKING: [cls.OUTDOOR_ACTIVITY, cls.FITNESS],
            # cls.CROSS_COUNTRY_SKIING: [cls.BUSHWALKING, cls.OUTDOOR_ACTIVITY, cls.FITNESS],
        }

        return dependencies.get(journal_type, [])
