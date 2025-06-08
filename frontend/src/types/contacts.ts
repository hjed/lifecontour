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
  street_address: string;
  suburb?: string;
  state?: string;
  postcode?: string;
  country: string;
  address_type?: string;
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

// Contact Types
export interface ContactAttributes {
  first_name: string;
  last_name?: string;
  organisation?: string;
  job_title?: string;
  created_at: string;
  updated_at: string;
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
  organisation?: string;
  job_title?: string;
  methods?: Omit<ContactMethodAttributes, 'id'>[];
  addresses?: Omit<ContactAddressAttributes, 'id'>[];
  notes?: Omit<ContactNoteAttributes, 'id' | 'created_at' | 'updated_at'>[];
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

// Contact Display Types (for UI)
export interface ContactDisplay {
  id: string;
  name: string;
  organisation?: string;
  job_title?: string;
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
  organisation?: string;
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
