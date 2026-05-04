from enum import StrEnum


class OutdoorActivitySubtype(StrEnum):
    """
    Enumeration of outdoor activity subtypes.

    Used for OUTDOOR_TRAINING focus areas and OUTDOOR_PLANNING activity types.
    """

    BUSHWALKING = "bushwalking"
    ABSEILING_TRIP = "abseiling_trip"
    CANYONING = "canyoning"
    CLIMBING = "climbing"
    KAYAKING = "kayaking"
    CROSS_COUNTRY_SKIING = "cross_country_skiing"
    CAVING = "caving"
    CANOEING = "canoeing"
    SNORKELLING = "snorkelling"
    DIVING = "diving"
    DOWNHILL_SKIING = "downhill_skiing"
    OUTDOOR_TRAINING = "outdoor_training"
