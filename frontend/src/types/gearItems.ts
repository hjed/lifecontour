/**
 * Gear Items types matching backend API schemas.
 */

import { JsonApiLinks, JsonApiMeta } from './api';

export interface GearItemAttributes {
  name: string;
  model?: string | null;
  serial_number?: string | null;
  purchase_date?: string | null;
  manufacturer?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface GearItemResource {
  type: 'gear-items';
  id: string;
  attributes: GearItemAttributes;
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

export type GearItem = GearItemResource['attributes'] & { id: string };

export interface GearItemListResponse {
  data: GearItemResource[];
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

export interface GearItemResponse {
  data: GearItemResource;
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

export interface GearItemCreateData {
  type: 'gear-items';
  attributes: Omit<GearItemAttributes, 'created_at' | 'updated_at'>;
}

export interface GearItemCreateRequest {
  data: GearItemCreateData;
}

export interface GearItemUpdateData {
  type: 'gear-items';
  id: string;
  attributes: Partial<Omit<GearItemAttributes, 'created_at' | 'updated_at'>>;
}

export interface GearItemUpdateRequest {
  data: GearItemUpdateData;
}
