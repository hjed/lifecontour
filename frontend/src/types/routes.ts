/**
 * Route-related types matching backend API schemas.
 */

import { JsonApiLinks, JsonApiMeta } from './api';

export interface RouteAttributes {
  name: string;
  description?: string | null;
  gpx_data?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}
export interface RouteResource {
  type: 'routes';
  id: string;
  attributes: RouteAttributes;
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

export type Route = RouteResource['attributes'] & { id: string };

export interface RouteResponse {
  data: RouteResource;
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

export interface RouteListResponse {
  data: RouteResource[];
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

export interface RouteFormData {
  name: string;
  description?: string | null;
  gpx_data?: string | null;
}

export interface RouteFilters {
  name?: string;
  page?: number;
  limit?: number;
}
