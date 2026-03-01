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
  CLIMBING = 'climbing',
  KAYAKING = 'kayaking',
  CROSS_COUNTRY_SKIING = 'cross_country_skiing',
}

// Journal Contact Relationship Type Enum
export enum JournalContactRelationshipType {
  PARTICIPANT = 'PARTICIPANT',
  INVITEE = 'INVITEE',
  MENTION = 'MENTION',
  ABOUT = 'ABOUT',
}

// Event Date Range
export interface EventDateRange {
  start: string; // ISO datetime string
  end: string; // ISO datetime string
}

// Type-specific data schemas
export interface CalendarInfoData {
  calendar_id: string;
  start_time?: string | null; // time string (HH:MM:SS)
  end_time?: string | null; // time string (HH:MM:SS)
  is_all_day: boolean;
  location?: string | null;
  sync_invitees: boolean;
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
  gpx_track_data?: string | null;
  strava_activity_id?: string | null;
}

export interface OutdoorActivityData {
  activity_type?: string | null;
  weather_conditions?: string | null;
  role?: string | null;
  in_leadership_role?: boolean | null;
  participant_notes?: string | null;
}

export interface BushwalkingData {
  route_id?: string | null;
  track_grading?: string | null;
}

export interface JoggingData {
  route_id?: string | null;
  pace?: number | null; // seconds per kilometre
}

export interface AbseilingData {
  number_of_abseils?: number | null;
  total_length?: number | null; // total length in metres
}

export interface CanyoningData {
  route_id?: string | null; // UUID of associated route
  french_grade?: string | null; // French canyoning grade
  water_guage_name?: string | null; // Name of the water gauge
  water_guage_level?: number | null; // Water gauge reading
  is_vertical?: boolean | null;
  is_night_canyon?: boolean | null;
  is_white_water?: boolean | null;
}

export interface ClimbingData {
  route_id?: string | null; // UUID of associated route
  climbing_type?: string | null; // e.g. sport, trad, bouldering
  grade?: number | null;
  length?: number | null; // length in metres
}

export interface KayakingData {
  route_id?: string | null; // UUID of associated route
  water_type?: string | null; // Type of water (e.g. river, lake, sea)
}

export interface CrossCountrySkiingData {
  route_id?: string | null; // UUID of associated route
  snow_conditions?: string | null; // Description of snow conditions
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
  | FitnessData
  | OutdoorActivityData
  | BushwalkingData
  | JoggingData
  | AbseilingData
  | CanyoningData
  | ClimbingData
  | KayakingData
  | CrossCountrySkiingData;

// Contact Relationship
export interface JournalContactRelationship {
  id: string; // Contact ID is returned as string from API
  name?: string | null;
  relationship_type: JournalContactRelationshipType;
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
