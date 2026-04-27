/**
 * Search-related types matching backend search API schemas.
 *
 * These types provide type safety for search functionality
 * including MeiliSearch responses and global search.
 */

import { JsonApiResource, PaginationMeta, JsonApiLinks } from './api';
import { ContactResource } from './contacts';

// Search Result Types
export interface SearchResultAttributes {
  entity_type: string;
  entity_id: string;
  title: string;
  content: string;
  highlighted_content?: string;
  score: number;
  matched_terms: string[];
  created_at: string;
  updated_at: string;
  [key: string]: unknown;
}

export interface SearchResultResource extends JsonApiResource<SearchResultAttributes> {
  type: 'search-results';
}

// Search Meta Types
export interface SearchMeta extends PaginationMeta {
  query: string;
  processing_time_ms: number;
  estimated_total_hits: number;
  facet_distribution?: Record<string, Record<string, number>>;
}

export interface ContactSearchMeta extends SearchMeta {
  tags_distribution?: Record<string, number>;
  organisation_distribution?: Record<string, number>;
}

export interface GlobalSearchMeta extends SearchMeta {
  entity_type_distribution?: Record<string, number>;
  [key: string]: unknown;
}

// Search Response Types
export interface ContactSearchResponse {
  data: ContactResource[];
  included?: JsonApiResource[];
  links?: JsonApiLinks;
  meta: ContactSearchMeta;
}

export interface GlobalSearchResponse {
  data: (SearchResultResource | ContactResource)[];
  included?: JsonApiResource[];
  links?: JsonApiLinks;
  meta: GlobalSearchMeta;
}

// Search Suggestions Types
export interface SearchSuggestion {
  text: string;
  highlighted: string;
  score: number;
}

export interface SearchSuggestionsResponse {
  suggestions: SearchSuggestion[];
  meta: {
    query: string;
    entity_type: string;
    processing_time_ms: number;
  };
}

// Search Health Types
export interface SearchHealthResponse {
  status: 'healthy' | 'degraded' | 'error';
  meilisearch_status: string;
  indices: string[];
  error?: string;
}

// Search Filter Types
export interface ContactSearchFilters {
  q: string;
  tags?: string[];
  sort?: string[];
  page?: number;
  limit?: number;
}

export interface GlobalSearchFilters {
  q: string;
  entity_types?: string[];
  page?: number;
  limit?: number;
}

export interface SearchSuggestionsFilters {
  q: string;
  entity_type?: string;
  limit?: number;
}

// Search State Types (for UI)
export interface SearchState {
  query: string;
  isLoading: boolean;
  results: SearchResultResource[] | ContactResource[];
  suggestions: SearchSuggestion[];
  meta?: SearchMeta;
  error?: string;
}

export interface SearchFiltersState {
  tags: string[];
  entity_types: string[];
  date_range?: {
    start: string;
    end: string;
  };
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
}

// Search Highlight Types
export interface HighlightMatch {
  text: string;
  isHighlighted: boolean;
}

export interface SearchHighlight {
  field: string;
  matches: HighlightMatch[];
}

// Search Analytics Types
export interface SearchAnalytics {
  popular_queries: Array<{
    query: string;
    count: number;
  }>;
  search_trends: Array<{
    date: string;
    searches: number;
  }>;
  entity_type_usage: Record<string, number>;
}

// Entity Types for Global Search
export const ENTITY_TYPES = [
  'contacts',
  'journal_entries',
  'calendar_events',
  'albums',
] as const;

export type EntityType = (typeof ENTITY_TYPES)[number];

// Search Sort Options
export const SEARCH_SORT_OPTIONS = [
  { value: 'relevance', label: 'Relevance' },
  { value: 'created_at:desc', label: 'Newest First' },
  { value: 'created_at:asc', label: 'Oldest First' },
  { value: 'updated_at:desc', label: 'Recently Updated' },
  { value: 'name:asc', label: 'Name A-Z' },
  { value: 'name:desc', label: 'Name Z-A' },
] as const;

export type SearchSortOption = (typeof SEARCH_SORT_OPTIONS)[number]['value'];
