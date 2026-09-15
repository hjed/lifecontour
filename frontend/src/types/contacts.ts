/**
 * Contact-related types matching backend API schemas.
 *
 * These types provide type safety for contact management
 * and match the backend Pydantic models.
 */

import {
  JsonApiResource,
  JsonApiResponse,
  JsonApiCollectionResponse,
  JsonApiLinks,
  JsonApiMeta,
} from './api';

// Contact Method Types
export enum ContactMethodType {
  EMAIL = 'email',
  PHONE = 'phone',
  MOBILE = 'mobile',
  FAX = 'fax',
  WEBSITE = 'website',
  SOCIAL = 'social',
}

export interface ContactMethodAttributes {
  method_type: ContactMethodType;
  value: string;
  label?: string;
  is_primary: boolean;
}

export interface ContactMethodResource extends Omit<
  JsonApiResource<ContactMethodAttributes>,
  'relationships'
> {
  type: 'contact_methods';
}

// Contact Address Types
export interface ContactAddressAttributes {
  label?: string;
  street_line_1: string;
  street_line_2?: string;
  locality?: string; // city
  region?: string; // state
  postal_code?: string;
  country_code: string;
  is_primary: boolean;
}

export interface ContactAddressResource extends Omit<
  JsonApiResource<ContactAddressAttributes>,
  'relationships'
> {
  type: 'contact_addresses';
}

// Contact Note Types
export interface ContactNoteAttributes {
  content: string;
  created_at: string;
  updated_at: string;
}

export interface ContactNoteResource extends Omit<
  JsonApiResource<ContactNoteAttributes>,
  'relationships'
> {
  type: 'contact_notes';
}

// Custom Date Types
export interface CustomDateTypeAttributes {
  name: string;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface CustomDateTypeResource extends Omit<
  JsonApiResource<CustomDateTypeAttributes>,
  'relationships'
> {
  type: 'custom_date_types';
}

// Important Date Types
export enum ImportantDatePrecision {
  FULL = 'full',
  DAY_MONTH = 'day_month',
  YEAR = 'year',
}

export enum ImportantDateTypeEnum {
  BIRTHDAY = 'birthday',
  ANNIVERSARY_MARRIAGE = 'marriage_anniversary',
  ANNIVERSARY_WORK = 'work_anniversary',
  FIRST_MET = 'first_met',
  CUSTOM = 'custom',
}

export interface ImportantDateAttributes {
  date_type: ImportantDateTypeEnum | string;
  precision: ImportantDatePrecision | string;
  year?: number | null;
  month?: number | null;
  day?: number | null;
  custom_date_type_id?: number | null;
  custom_date_type_name?: string | null;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface ImportantDateResource {
  id?: number | string | null;
  type: 'important_dates';
  attributes: ImportantDateAttributes;
}

// Tag Types
export interface TagAttributes {
  name: string;
  color?: string;
  description?: string;
  parent_id?: number | null;
  created_at: string;
  updated_at: string;
  [key: string]: unknown;
}

export interface TagResource extends Omit<
  JsonApiResource<TagAttributes>,
  'relationships'
> {
  type: 'tags';
}

// Contact Relationship Types
export enum RelationshipType {
  PARENT = 'parent',
  CHILD = 'child',
  SIBLING = 'sibling',
  PARTNER = 'partner',
  FRIEND = 'friend',
  COLLEAGUE = 'colleague',
  FAMILY = 'family',
  OTHER = 'other',
}

export interface ContactRelationshipAttributes {
  from_contact_id: number;
  to_contact_id: number | null;
  to_contact_name?: string;
  to_user: boolean;
  relationship_type: RelationshipType;
  created_at: string;
  updated_at: string;
}

export interface ContactRelationshipResource extends Omit<
  JsonApiResource<ContactRelationshipAttributes>,
  'relationships'
> {
  type: 'contact_relationships';
}

// Contact Summary Types
export enum ContactSummaryStatus {
  PENDING = 'pending',
  GENERATING = 'generating',
  GENERATED = 'generated',
  FAILED = 'failed',
  DISABLED = 'disabled',
}

/**
 * Why AI summary generation is disabled for a contact.
 *
 * `USER` is the user's own choice and stays off. `LOW_ACTIVITY` is an
 * automatic pause that resumes once the contact has enough recent activity.
 */
export enum ContactSummaryDisabledReason {
  USER = 'user',
  LOW_ACTIVITY = 'low_activity',
}

export interface ContactSummaryAttributes {
  summary_text: string | null;
  follow_up_suggestions: string[];
  status: ContactSummaryStatus;
  is_disabled: boolean;
  /** Null when generation is enabled. */
  disabled_reason: ContactSummaryDisabledReason | null;
  is_user_override: boolean;
  user_override_text: string | null;
  generated_at: string | null;
}

export interface ContactSummaryResource {
  type: 'contact_summaries';
  id: string;
  attributes: ContactSummaryAttributes;
}

/** Body attributes for `PATCH /api/contacts/{id}/summary`. */
export interface ContactSummaryUpdateData {
  /** Turn AI generation off (`true`) or back on (`false`). */
  is_disabled?: boolean;
  /** Manual summary text; `null` clears an existing override. */
  user_override_text?: string | null;
}

// Contact Types
export interface ContactAttributes {
  first_name: string;
  last_name?: string;
  middle_name?: string;
  nick_name?: string;
  is_favourite?: boolean;
  photo_url?: string | null;
  created_at: string;
  updated_at: string;
  // Embedded related data (not separate resources for REST API)
  contact_methods: ContactMethodResource[];
  addresses: ContactAddressResource[];
  notes: ContactNoteResource[];
  relationships: ContactRelationshipResource[];
  important_dates?: ImportantDateResource[];
  summary?: ContactSummaryResource | null;
}

export interface ContactRelationships {
  methods?: {
    data?: ContactMethodResource[] | null;
    links?: JsonApiLinks;
    meta?: JsonApiMeta;
  };
  addresses?: {
    data?: ContactAddressResource[] | null;
    links?: JsonApiLinks;
    meta?: JsonApiMeta;
  };
  notes?: {
    data?: ContactNoteResource[] | null;
    links?: JsonApiLinks;
    meta?: JsonApiMeta;
  };
  tags?: {
    data?: TagResource[] | null;
    links?: JsonApiLinks;
    meta?: JsonApiMeta;
  };
}

export interface ContactResource {
  type: 'contacts';
  id: string;
  attributes: ContactAttributes;
  relationships?: ContactRelationships;
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

// API Response Types
export interface ContactResponse {
  data: ContactResource;
  included?: JsonApiResource[];
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

export interface ContactListResponse {
  data: ContactResource[];
  included?: JsonApiResource[];
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

/**
 * Per-field conflict-resolution overrides for a contact merge (ITER13-003).
 *
 * Each key is the concrete value to apply to the surviving contact — the caller
 * has already resolved the survivor / source / custom choice. Omitted keys fall
 * back to the backend default policy (survivor wins, prefer non-empty). Mirrors
 * the backend `MergeContactOverrides` schema and the journal `MergeOverrides`
 * shape. `company`/`job_title` are part of the contract for MCP/API parity even
 * though the web resource does not currently expose them.
 */
export interface MergeContactOverrides {
  first_name?: string;
  last_name?: string;
  middle_name?: string;
  nick_name?: string;
  company?: string;
  job_title?: string;
  photo_url?: string;
  is_favourite?: boolean;
}
export type TagResponse = JsonApiResponse<TagResource>;
export type TagListResponse = JsonApiCollectionResponse<TagResource>;

export type CustomDateTypeResponse = JsonApiResponse<CustomDateTypeResource>;
export type CustomDateTypeListResponse =
  JsonApiCollectionResponse<CustomDateTypeResource>;

export interface ContactFieldAttributes {
  field_name: string;
  field_type: string;
  entity_id?: number | null;
  old_value?: string | null;
  new_value?: string | null;
  updated_at: string;
  [key: string]: unknown;
}

export interface ContactFieldResource {
  id: string;
  type: 'contact_fields';
  attributes: ContactFieldAttributes;
}

export interface ContactFieldResponse {
  data: ContactFieldResource;
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

// Form Data Types (for creating/updating)
export interface ContactFormData {
  first_name: string;
  last_name?: string;
  middle_name?: string;
  nick_name?: string;
  contact_methods?: ContactMethodResource[];
  addresses?: ContactAddressResource[];
  notes?: ContactNoteResource[];
  important_dates?: ImportantDateResource[];
}

export interface ContactCreateData {
  type: 'contacts';
  attributes: ContactFormData;
}

export interface ContactUpdateData {
  type: 'contacts';
  id: string;
  attributes: ContactFormData;
}

// Tag Create Types
export interface TagCreateAttributes {
  name: string;
  color?: string;
  description?: string;
  parent_id?: number | null;
}

export interface TagCreateData {
  type: 'tags';
  attributes: TagCreateAttributes;
}

export interface TagCreateRequest {
  data: TagCreateData;
}

// Tag Assignment Types
export interface TagAssignmentData {
  type: 'tags';
  id: string;
}

export interface TagAssignmentRequest {
  data: TagAssignmentData;
}

// Contact Relationship API Types
export interface ContactRelationshipFormData {
  from_contact_id: number;
  to_contact_id?: number;
  to_user?: boolean;
  relationship_type: RelationshipType;
}

export interface ContactRelationshipCreateData {
  type: 'contact_relationships';
  attributes: ContactRelationshipFormData;
}

export interface ContactRelationshipUpdateData {
  type: 'contact_relationships';
  id: string;
  attributes: ContactRelationshipFormData;
}

export interface ContactRelationshipCreateRequest {
  data: ContactRelationshipCreateData;
}

export interface ContactRelationshipUpdateRequest {
  data: ContactRelationshipUpdateData;
}

export interface ContactRelationshipResponse {
  data: ContactRelationshipResource;
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

export interface ContactRelationshipListResponse {
  data: ContactRelationshipResource[];
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

// Contact Display Types (for UI)
export interface ContactDisplay {
  id: string;
  name: string;
  primary_email?: string;
  primary_phone?: string;
  tags: TagAttributes[];
  created_at: string;
  updated_at: string;
}

// Contact Filter Types
export interface ContactFilters {
  search?: string;
  tags?: string[];
  favourite?: boolean;
  created_after?: string;
  created_before?: string;
  page?: number;
  limit?: number;
}

// Predefined Tag Colors (Australian theme)
export const TAG_COLORS = [
  '#E53E3E', // Red
  '#DD6B20', // Orange
  '#D69E2E', // Yellow
  '#38A169', // Green
  '#319795', // Teal
  '#3182CE', // Blue
  '#805AD5', // Purple
  '#D53F8C', // Pink
  '#718096', // Gray
  '#2D3748', // Dark Gray
] as const;

export type TagColor = (typeof TAG_COLORS)[number];

// Contact History/Activity Types.
// History is entity-agnostic and lives in `types/history.ts`; these aliases are
// retained for backward compatibility.
export type {
  HistoryAttributes as ContactHistoryAttributes,
  HistoryResource as ContactHistoryResource,
  HistoryPaginationMeta as ContactHistoryPaginationMeta,
  HistoryListResponse as ContactHistoryListResponse,
} from './history';
