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

export interface ContactMethodResource
  extends Omit<JsonApiResource<ContactMethodAttributes>, 'relationships'> {
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

export interface ContactAddressResource
  extends Omit<JsonApiResource<ContactAddressAttributes>, 'relationships'> {
  type: 'contact_addresses';
}

// Contact Note Types
export interface ContactNoteAttributes {
  content: string;
  created_at: string;
  updated_at: string;
}

export interface ContactNoteResource
  extends Omit<JsonApiResource<ContactNoteAttributes>, 'relationships'> {
  type: 'contact_notes';
}

// Tag Types
export interface TagAttributes {
  name: string;
  color?: string;
  description?: string;
  created_at: string;
  updated_at: string;
  [key: string]: unknown;
}

export interface TagResource
  extends Omit<JsonApiResource<TagAttributes>, 'relationships'> {
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
  to_contact_id: number;
  relationship_type: RelationshipType;
  created_at: string;
  updated_at: string;
}

export interface ContactRelationshipResource
  extends Omit<
    JsonApiResource<ContactRelationshipAttributes>,
    'relationships'
  > {
  type: 'contact_relationships';
}

// Contact Types
export interface ContactAttributes {
  first_name: string;
  last_name?: string;
  middle_name?: string;
  nick_name?: string;
  is_favourite?: boolean;
  created_at: string;
  updated_at: string;
  // Embedded related data (not separate resources for REST API)
  contact_methods: ContactMethodResource[];
  addresses: ContactAddressResource[];
  notes: ContactNoteResource[];
  relationships: ContactRelationshipResource[];
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
export type TagResponse = JsonApiResponse<TagResource>;
export type TagListResponse = JsonApiCollectionResponse<TagResource>;

// Form Data Types (for creating/updating)
export interface ContactFormData {
  first_name: string;
  last_name?: string;
  middle_name?: string;
  nick_name?: string;
  contact_methods?: ContactMethodResource[];
  addresses?: ContactAddressResource[];
  notes?: ContactNoteResource[];
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
  to_contact_id: number;
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

// Contact History/Activity Types
export interface ContactHistoryAttributes {
  entity_type: string;
  entity_id: number;
  field_name: string;
  old_value: string | null;
  new_value: string | null;
  changed_by: string | null;
  created_at: string | null;
}

export interface ContactHistoryResource {
  type: 'contact_history';
  id: string;
  attributes: ContactHistoryAttributes;
}

export interface ContactHistoryPaginationMeta {
  total_count: number;
  page_count: number;
  current_page: number;
  per_page: number;
}

export interface ContactHistoryListResponse {
  data: ContactHistoryResource[];
  meta?: ContactHistoryPaginationMeta;
  links?: JsonApiLinks;
}
