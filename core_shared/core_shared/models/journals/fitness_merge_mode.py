"""How fitness data is combined when two journals are merged.

A fitness journal records a single bout of activity, so merging two of them is
not the same problem as merging two descriptions of the same thing. Two Strava
activities that describe one outing (a ride split by a stopped recording, a run
logged on two devices) add up: the merged journal covers both, and both remain
linked to their remote activity.

The mode is chosen per merge because both readings are legitimate — the same
merge endpoint also resolves genuine duplicates, where one set of numbers is
simply right and the other is a re-import to be discarded.
"""

from enum import StrEnum


class FitnessMergeMode(StrEnum):
    """Strategy for reconciling two journals' ``journal_fitness_data`` rows.

    Values:
        REPLACE: Treat the rows as rival descriptions of one activity. The
            target's values stand, the source fills only the gaps, and the
            source's integration links are dropped.
        ADDITIVE: Treat the rows as two parts of one outing. Distances,
            durations, elevations and calories sum, heart rates combine, and
            every one of the source's integration links carries over so both
            remote activities stay linked to the survivor.
    """

    REPLACE = "replace"
    ADDITIVE = "additive"
