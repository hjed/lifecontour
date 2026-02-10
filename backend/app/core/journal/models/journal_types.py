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

    # Activity types (Iteration 4.5) - placeholder for documentation
    # FITNESS = "fitness"
    # OUTDOOR_ACTIVITY = "outdoor_activity"
    # BUSHWALKING = "bushwalking"
    # ABSEILING_TRIP = "abseiling_trip"
    # CANYONING = "canyoning"
    # CLIMBING = "climbing"
    # KAYAKING = "kayaking"
    # CROSS_COUNTRY_SKIING = "cross_country_skiing"
    # JOGGING = "jogging"

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
        # Type dependency mapping (will be expanded in Iteration 4.5)
        dependencies: dict[JournalType, list[JournalType]] = {
            # Base types have no dependencies
            cls.NOTE: [],
            cls.EVENT: [],
            cls.MOOD_RATING: [],
            cls.PLAN: [],
            cls.TRAVEL: [],
            cls.PHOTO_ALBUM: [],
            # Future fitness types will be added here in Iteration 4.5
            # cls.FITNESS: [],
            # cls.OUTDOOR_ACTIVITY: [cls.FITNESS],
            # cls.BUSHWALKING: [cls.OUTDOOR_ACTIVITY, cls.FITNESS],
            # cls.ABSEILING_TRIP: [cls.OUTDOOR_ACTIVITY, cls.FITNESS],
            # cls.CANYONING: [cls.BUSHWALKING, cls.ABSEILING_TRIP, cls.OUTDOOR_ACTIVITY, cls.FITNESS],
            # cls.CLIMBING: [cls.OUTDOOR_ACTIVITY, cls.FITNESS],
            # cls.KAYAKING: [cls.OUTDOOR_ACTIVITY, cls.FITNESS],
            # cls.CROSS_COUNTRY_SKIING: [cls.BUSHWALKING, cls.OUTDOOR_ACTIVITY, cls.FITNESS],
            # cls.JOGGING: [cls.FITNESS],
        }

        return dependencies.get(journal_type, [])
