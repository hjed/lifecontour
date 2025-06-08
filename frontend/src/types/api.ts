/**
 * Common API types following JSON API specification.
 *
 * These types match the backend JSON API responses and provide
 * type safety for frontend API interactions.
 */

// JSON API Base Types
export interface JsonApiLinks {
  self?: string;
  related?: string;
  first?: string;
  last?: string;
  prev?: string;
  next?: string;
}

export interface JsonApiMeta {
  [key: string]: unknown;
}

export interface JsonApiError {
  id?: string;
  status?: string;
  code?: string;
  title?: string;
  detail?: string;
  source?: {
    pointer?: string;
    parameter?: string;
  };
  meta?: JsonApiMeta;
}

export interface JsonApiResource<T = Record<string, unknown>> {
  type: string;
  id: string;
  attributes: T;
  relationships?: {
    [key: string]: {
      data?: JsonApiResource | JsonApiResource[] | null;
      links?: JsonApiLinks;
      meta?: JsonApiMeta;
    };
  };
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

export interface JsonApiResponse<T extends JsonApiResource> {
  data: T;
  included?: JsonApiResource[];
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

export interface JsonApiCollectionResponse<T extends JsonApiResource> {
  data: T[];
  included?: JsonApiResource[];
  links?: JsonApiLinks;
  meta?: JsonApiMeta;
}

export interface JsonApiErrorResponse {
  errors: JsonApiError[];
  meta?: JsonApiMeta;
}

// Pagination Types
export interface PaginationMeta {
  total: number;
  page: number;
  limit: number;
  totalPages: number;
}

// API Request Types
export interface JsonApiCreateRequest<T> {
  data: T;
}

export interface JsonApiUpdateRequest<T> {
  data: T;
}

// Common API Response Wrapper
export type ApiResponse<T> = T | JsonApiErrorResponse;

// HTTP Methods
export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

// API Client Configuration
export interface ApiClientConfig {
  baseUrl: string;
  timeout?: number;
  headers?: Record<string, string>;
}

// Request Options
export interface RequestOptions {
  method?: HttpMethod;
  headers?: Record<string, string>;
  body?: string | FormData | URLSearchParams | null;
  signal?: AbortSignal;
}
