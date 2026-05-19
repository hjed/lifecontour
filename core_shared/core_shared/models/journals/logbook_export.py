"""Domain models for logbook export data contracts."""

from dataclasses import dataclass, field

from .abseil_pitch import AbseilPitch
from .abseiling_data import AbseilingData
from .bushwalking_data import BushwalkingData
from .canoeing_data import CanoeingData
from .canyoning_data import CanyoningData
from .caving_data import CavingData
from .climbing_data import ClimbingData
from .cross_country_skiing_data import CrossCountrySkiingData
from .diving_data import DivingData
from .downhill_skiing_data import DownhillSkiingData
from .fitness_data import FitnessData
from .gear_maintenance_data import GearMaintenanceData
from .kayaking_data import KayakingData
from .outdoor_activity_data import OutdoorActivityData
from .outdoor_planning_data import OutdoorPlanningData
from .outdoor_training_data import OutdoorTrainingData
from .snorkelling_data import SnorkellingData
from .value_objects import EventDateRange


@dataclass
class LogbookEntryContact:
    """Contact information for a logbook entry participant or invitee."""

    contact_id: int
    name: str
    role: str  # e.g., 'PARTICIPANT', 'INVITEE'


@dataclass
class LogbookEntryData:
    """A complete hierarchical entry for the logbook export."""

    id: int
    title: str
    content: str
    event_date_range: EventDateRange
    parent_id: int | None

    # Nested children
    children: list[LogbookEntryData] = field(default_factory=list)

    # Types list
    journal_types: list[str] = field(default_factory=list)

    # Contacts
    contacts: list[LogbookEntryContact] = field(default_factory=list)

    # Type-specific data references
    outdoor_activity_data: OutdoorActivityData | None = None
    fitness_data: FitnessData | None = None
    bushwalking_data: BushwalkingData | None = None
    abseiling_data: AbseilingData | None = None
    abseil_pitches: list[AbseilPitch] = field(default_factory=list)
    canyoning_data: CanyoningData | None = None
    climbing_data: ClimbingData | None = None
    kayaking_data: KayakingData | None = None
    cross_country_skiing_data: CrossCountrySkiingData | None = None
    caving_data: CavingData | None = None
    canoeing_data: CanoeingData | None = None
    snorkelling_data: SnorkellingData | None = None
    diving_data: DivingData | None = None
    downhill_skiing_data: DownhillSkiingData | None = None
    outdoor_training_data: OutdoorTrainingData | None = None
    outdoor_planning_data: OutdoorPlanningData | None = None
    gear_maintenance_data: GearMaintenanceData | None = None

    # Additional enriched data
    template_name: str | None = None
    gear_item_name: str | None = None


@dataclass
class LogbookYearlySummary:
    """Summary statistics for a calendar year."""

    year: int
    total_activities_by_type: dict[str, int] = field(default_factory=dict)
    leadership_activities_by_type: dict[str, int] = field(default_factory=dict)
    total_abseiling_metres: int = 0
    total_abseils: int = 0
    total_setups: int = 0
    total_rescues: int = 0


@dataclass
class ParticipantIndexEntry:
    """Entry in the participant index."""

    contact_id: int
    name: str
    appearances: int


@dataclass
class LogbookExportData:
    """The complete data contract for rendering a logbook PDF."""

    entries: list[LogbookEntryData]  # Root entries chronologically ordered
    yearly_summaries: list[LogbookYearlySummary]
    participant_index: list[ParticipantIndexEntry]
