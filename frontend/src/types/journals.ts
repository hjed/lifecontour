/**
 * Journal-related types matching backend API schemas.
 *
 * These types provide type safety for journal management
 * and match the backend Pydantic models.
 */

import { JsonApiResource, JsonApiLinks, JsonApiMeta } from './api';

// Journal Type Enum
// Values must match backend JournalType enum (lowercase)
export enum JournalType {
  NOTE = 'note',
  EVENT = 'event',
  MOOD_RATING = 'mood_rating',
  PLAN = 'plan',
  TRAVEL = 'travel',
  PHOTO_ALBUM = 'photo_album',
  // Activity types (Iteration 4.5)
  FITNESS = 'fitness',
  OUTDOOR_ACTIVITY = 'outdoor_activity',
  BUSHWALKING = 'bushwalking',
  JOGGING = 'jogging',
  ABSEILING_TRIP = 'abseiling_trip',
  CANYONING = 'canyoning',
  CAVING = 'caving',
  CANOEING = 'canoeing',
  CLIMBING = 'climbing',
  KAYAKING = 'kayaking',
  CROSS_COUNTRY_SKIING = 'cross_country_skiing',
  SNORKELLING = 'snorkelling',
  DIVING = 'diving',
  DOWNHILL_SKIING = 'downhill_skiing',
  OUTDOOR_PLANNING = 'outdoor_planning',
  GEAR_MAINTENANCE = 'gear_maintenance',
}

// Journal Contact Relationship Type Enum
export enum JournalContactRelationshipType {
  PARTICIPANT = 'PARTICIPANT',
  INVITEE = 'INVITEE',
  MENTION = 'MENTION',
  ABOUT = 'ABOUT',
}

// Attendee Status Enum
export enum AttendeeStatus {
  ATTENDING = 'ATTENDING',
  ATTENDED = 'ATTENDED',
  MAYBE = 'MAYBE',
  NO_REPLY = 'NO_REPLY',
  DECLINED = 'DECLINED',
}

// Contact Event Role Enum
export enum ContactEventRole {
  ORGANISER = 'ORGANISER',
  FACILITATOR_HELPER = 'FACILITATOR_HELPER',
}

// Event Date Range
export interface EventDateRange {
  start: string; // ISO datetime string
  end: string; // ISO datetime string
}

// Event State Enum
// Values must match backend EventState enum (lowercase)
export enum EventState {
  INVITED = 'invited',
  TENTATIVE = 'tentative',
  CONFIRMED = 'confirmed',
  CANCELLED = 'cancelled',
}

// Type-specific data schemas
export interface CalendarInfoData {
  calendar_id: string;
  start_time?: string | null; // time string (HH:MM:SS)
  end_time?: string | null; // time string (HH:MM:SS)
  is_all_day: boolean;
  location?: string | null;
  timezone?: string | null; // IANA timezone (e.g. 'Australia/Sydney')
  sync_invitees: boolean;
  event_state?: EventState;
}

export interface MoodData {
  mood_value?: number | null; // 1-10
  mood_label?: string | null;
  energy_level?: number | null; // 1-10
}

export interface PlanDocument {
  id?: string | null;
  url: string;
  title?: string | null;
  description?: string | null;
  order?: number | null;
}

export interface PlanData {
  documents: PlanDocument[];
}

export interface Coordinate {
  latitude: number;
  longitude: number;
  elevation?: number;
  timestamp?: string;
}

export interface TravelFlight {
  id?: string | null;
  flight_number?: string | null;
  airline?: string | null;
  departure_airport?: string | null;
  arrival_airport?: string | null;
  departure_time?: string | null; // ISO datetime string
  arrival_time?: string | null; // ISO datetime string
  booking_reference?: string | null;
  confirmation_number?: string | null;
  order?: number | null;
}

export interface TravelAccommodation {
  id?: string | null;
  name: string;
  address?: string | null;
  location?: string | null; // Location/city of accommodation
  check_in_date?: string | null; // ISO date string
  check_out_date?: string | null; // ISO date string
  booking_reference?: string | null;
  confirmation_number?: string | null;
  order?: number | null;
}

export interface TravelTransportation {
  id?: string | null;
  type: string;
  details?: string | null;
  booking_reference?: string | null;
  order?: number | null;
}

export interface TravelData {
  flights: TravelFlight[];
  accommodations: TravelAccommodation[];
  transportation: TravelTransportation[];
}

export interface PhotoAlbumData {
  immich_album_id?: string | null;
}

export interface FitnessData {
  heart_rate_avg?: number | null;
  heart_rate_max?: number | null;
  distance?: number | null;
  elevation_gain?: number | null;
  elevation_loss?: number | null;
  duration?: number | null;
  calories?: number | null;
  strava_activity_id?: string | null;
  // Frontend-only field for handling multiple GPX tracks during create mode
  pending_routes?: { name: string; gpx_data: string }[];
}

export interface OutdoorActivityData {
  weather_conditions?: string | null;
  role?: string | null;
  in_leadership_role?: boolean | null;
  participant_notes?: string | null;
}

export interface BushwalkingData {
  track_grading?: string | null;
}

export interface JoggingData {
  pace?: number | null; // seconds per kilometre
}

export interface AbseilPitch {
  id?: number | null;
  pitch_number: number;
  height?: number | null;
  anchor_location?: string | null;
  anchor_type?: string | null;
  did_rescue?: boolean | null;
  did_setup?: boolean | null;
}

// Activity Templates
export enum ActivityTemplateType {
  CANYONING = 'canyoning',
  CAVING = 'caving',
  CLIMBING = 'climbing',
}

export interface TemplatePitch {
  id?: number | null;
  pitch_number: number;
  height?: number | null;
  anchor_location?: string | null;
  anchor_type?: string | null;
  did_rescue?: boolean | null;
  did_setup?: boolean | null;
}

export interface ActivityTemplateAttributes {
  name: string;
  template_type: ActivityTemplateType;
  region?: string | null;
  description?: string | null;
  pitches?: TemplatePitch[] | null;
  french_grade?: string | null;
  canyon_type?: string | null;
  water_gauge_name?: string | null;
  is_vertical?: boolean | null;
  is_horizontal?: boolean | null;
  climbing_type?: string | null;
  grade?: number | null;
  length?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ActivityTemplateResource {
  type: 'activity-templates';
  id: string;
  attributes: ActivityTemplateAttributes;
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

export interface ActivityTemplateResponse {
  data: ActivityTemplateResource;
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

export interface ActivityTemplateListResponse {
  data: ActivityTemplateResource[];
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

export interface ActivityTemplateCreateData {
  type: 'activity-templates';
  attributes: Omit<ActivityTemplateAttributes, 'created_at' | 'updated_at'>;
}

export interface ActivityTemplateCreateRequest {
  data: ActivityTemplateCreateData;
}

export interface ActivityTemplateUpdateData {
  type: 'activity-templates';
  id: string;
  attributes: Partial<ActivityTemplateAttributes>;
}

export interface ActivityTemplateUpdateRequest {
  data: ActivityTemplateUpdateData;
}

export interface AbseilingData {
  number_of_abseils?: number | null;
  total_length?: number | null; // total length in metres
  number_of_setups?: number | null;
  number_of_rescues?: number | null;
  pitches?: AbseilPitch[];
}

export interface CanyoningData {
  template_id?: string | null;
  french_grade?: string | null; // French canyoning grade
  water_guage_name?: string | null; // Name of the water gauge
  water_guage_level?: number | null; // Water gauge reading
  is_vertical?: boolean | null;
  is_night_canyon?: boolean | null;
  is_white_water?: boolean | null;
}

export interface CavingData {
  template_id?: string | null;
  is_vertical?: boolean | null;
  is_horizontal?: boolean | null;
}

export interface CanoeingData {
  water_type?: string | null;
}

export interface ClimbingData {
  template_id?: string | null;
  climbing_type?: string | null; // e.g. sport, trad, bouldering
  grade?: number | null;
  length?: number | null; // length in metres
}

export interface KayakingData {
  water_type?: string | null; // Type of water (e.g. river, lake, sea)
  is_white_water?: boolean | null; // Whether this is white water kayaking
  rapids_grade?: string | null; // International Scale of River Difficulty (I–VI)
}

export interface CrossCountrySkiingData {
  snow_conditions?: string | null; // Description of snow conditions
}

export interface OutdoorPlanningData {
  topics?: string | null;
  activity_types?: string[] | null;
}

export interface GearMaintenanceData {
  gear_item_id?: string | null;
  maintenance_type?: string | null;
  activity_types?: string[] | null;
  retirement_reason?: string | null;
}

// Type data union type
export type JournalTypeData =
  | CalendarInfoData
  | MoodData
  | PlanData
  | TravelData
  | PhotoAlbumData
  | FitnessData
  | OutdoorActivityData
  | BushwalkingData
  | JoggingData
  | AbseilingData
  | CanyoningData
  | CavingData
  | CanoeingData
  | ClimbingData
  | KayakingData
  | CrossCountrySkiingData
  | OutdoorPlanningData
  | GearMaintenanceData;

// Contact Relationship
export interface JournalContactRelationship {
  id: string; // Contact ID is returned as string from API
  name?: string | null;
  relationship_type: JournalContactRelationshipType;
  status?: AttendeeStatus | null;
  role?: ContactEventRole | null;
  first_name?: string | null;
  last_name?: string | null;
}

// Alias for backward compatibility
export type JournalContact = JournalContactRelationship;

// Journal Tag
export interface JournalTag {
  id: string; // UUID from backend
  name: string;
  color?: string | null;
}

// Calendar
export interface JournalCalendar {
  id: string;
  name: string;
  color?: string | null;
  description?: string | null;
  is_synced_to_google?: boolean;
  google_calendar_id?: string | null;
}

// Parent Journal Summary
export interface ParentJournalSummary {
  id: string;
  title: string;
}

// Child Journal Summary
export interface ChildJournalSummary {
  id: string;
  title: string;
  date?: string | null;
  types: JournalType[];
}

// Review Items and Suggestions
export interface ReviewSuggestion {
  id: number;
  reason: string;
  confidence_score: number;
  candidate_journal_id: number;
  candidate_journal_title: string;
}

export interface ReviewItemJournalSummary {
  id: number;
  title: string;
  event_date_range: { start: string; end: string };
}

export interface ReviewItemAttributes {
  status: string;
  reason: string;
  confidence_score: number;
  details: Record<string, unknown>;
  source_journal: ReviewItemJournalSummary;
  candidate_journal: ReviewItemJournalSummary;
}

export interface ReviewItemResource {
  type: 'review-items';
  id: string;
  attributes: ReviewItemAttributes;
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

export interface ReviewItemsListResponse {
  data: ReviewItemResource[];
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

// Journal Attributes
export interface JournalAttributes {
  title: string;
  content: string;
  event_date_range: EventDateRange;
  parent_id?: number | null;
  order?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  // Type information
  types: JournalType[];
  type_data?: Record<string, JournalTypeData>;
  // Embedded relationships
  contacts: JournalContactRelationship[];
  tags: JournalTag[];
  calendar?: JournalCalendar | null;
  // Hierarchy information
  parent?: ParentJournalSummary | null;
  children?: ChildJournalSummary[];
  children_count?: number | null;
  depth?: number | null;
  // Review information
  has_pending_reviews?: boolean;
  review_items?: ReviewSuggestion[];
}

// Journal Relationships
export interface JournalRelationships {
  tags?: {
    data?: JournalTag[] | null;
    links?: JsonApiLinks;
    meta?: JsonApiMeta;
  };
  contacts?: {
    data?: JournalContactRelationship[] | null;
    links?: JsonApiLinks;
    meta?: JsonApiMeta;
  };
  calendar?: {
    data?: JournalCalendar | null;
    links?: JsonApiLinks;
    meta?: JsonApiMeta;
  };
}

// Journal Resource
export interface JournalResource {
  type: 'journals';
  id: string;
  attributes: JournalAttributes;
  relationships?: JournalRelationships;
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

// Convenience type that combines resource and attributes
export type Journal = JournalResource['attributes'] & { id: string };

// API Response Types
export interface JournalResponse {
  data: JournalResource;
  included?: JsonApiResource[];
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

export interface JournalListResponse {
  data: JournalResource[];
  included?: JsonApiResource[];
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

// Form Data Types (for creating/updating)
export interface JournalFormData {
  title: string;
  content: string;
  event_date_range: EventDateRange;
  parent_id?: number | null;
  order?: number | null;
  types?: JournalType[];
  type_data?: Record<string, JournalTypeData>;
  contacts?: JournalContactRelationship[];
  tags?: JournalTag[];
}

export interface JournalCreateData {
  type: 'journals';
  attributes: JournalFormData;
}

export interface JournalUpdateData {
  type: 'journals';
  id: string;
  attributes: Partial<JournalFormData>;
}

export interface JournalCreateRequest {
  data: JournalCreateData;
}

export interface JournalUpdateRequest {
  data: JournalUpdateData;
}

// Filter Types
export interface ContactJournalsFilters {
  relationship_type?: string;
  page?: number;
  limit?: number;
}

export interface MergeOverrides {
  title?: string | null;
  content?: string | null;
  event_date_range?: { start: string; end: string } | null;
  type_data?: Record<string, Record<string, unknown>> | null;
}
export interface JournalFilters {
  search?: string;
  types?: JournalType[];
  contact_id?: string;
  tag_ids?: string[];
  calendar_id?: string;
  parent_id?: number | null;
  date_from?: string; // ISO date string
  date_to?: string; // ISO date string
  page?: number;
  limit?: number;
}

// Type Management Types
export interface JournalTypeAddData {
  type: 'journal-types';
  attributes: {
    journal_type: JournalType;
    type_data?: Record<string, unknown>;
  };
}

export interface JournalTypeAddRequest {
  data: JournalTypeAddData;
}

// Contact Relationship Management Types
export interface JournalContactRelationshipAddData {
  type: 'journal-contact-relationships';
  attributes: {
    contact_id: string;
    relationship_type: JournalContactRelationshipType;
    status?: AttendeeStatus | null;
    role?: ContactEventRole | null;
  };
}

export interface JournalContactRelationshipAddRequest {
  data: JournalContactRelationshipAddData;
}

// Tag Management Types
export interface JournalTagAddData {
  type: 'journal-tags';
  attributes: {
    tag_id: string;
  };
}

export interface JournalTagAddRequest {
  data: JournalTagAddData;
}

// Daily Summary Types
export enum DailySummaryStatus {
  PENDING = 'pending',
  GENERATING = 'generating',
  GENERATED = 'generated',
  FAILED = 'failed',
  DISABLED = 'disabled',
  OUTDATED = 'outdated',
}

export interface DailySummaryAttributes {
  summary_date: string;
  summary_text?: string | null;
  journal_count: number;
  event_count: number;
  contact_count: number;
  mood_average?: number | null;
  status: DailySummaryStatus;
}

export interface DailySummaryResource {
  type: 'journal-daily-summaries';
  id: string;
  attributes: DailySummaryAttributes;
}

export interface DailySummaryResponse {
  data: DailySummaryResource | null;
}

// Auto-merge response
export interface AutoMergeResultAttributes {
  merged_count: number;
  skipped_count: number;
  remaining_count: number;
  errors: string[];
}

export interface AutoMergeResponse {
  data: {
    type: 'auto-merge-result';
    attributes: AutoMergeResultAttributes;
  };
}
