/**
 * Journal API client functions using TanStack Query.
 *
 * Provides typed API functions for journal management operations
 * with proper error handling and caching.
 */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { toast } from 'sonner';
import { addDays, subDays, format, parseISO } from 'date-fns';
import {
  JournalListResponse,
  JournalResponse,
  JournalFormData,
  JournalFilters,
  JournalType,
  JournalContactRelationshipType,
  JournalTag,
  JournalSeries,
  JournalCalendar,
  MergeOverrides,
  ReviewItemsListResponse,
  AttendeeStatus,
  ContactEventRole,
  DailySummaryResponse,
  AutoMergeResponse,
} from '@/types/journals';
import { JsonApiErrorResponse, JsonApiMeta } from '@/types/api';
import type { HistoryFilters, HistoryListResponse } from '@/types/history';
import {
  API_ENDPOINTS,
  ERROR_MESSAGES,
  SUCCESS_MESSAGES,
} from '@/lib/constants';

// Query Keys
export const journalKeys = {
  all: ['journals'] as const,
  lists: () => [...journalKeys.all, 'list'] as const,
  list: (filters: JournalFilters) => [...journalKeys.lists(), filters] as const,
  infiniteLists: () => [...journalKeys.lists(), 'infinite'] as const,
  infiniteList: (
    filters: JournalFilters,
    options?: { chunkDays?: number; anchorDate?: string }
  ) => [...journalKeys.infiniteLists(), filters, options] as const,
  details: () => [...journalKeys.all, 'detail'] as const,
  detail: (id: string) => [...journalKeys.details(), id] as const,
  search: (query: string) => [...journalKeys.all, 'search', query] as const,
  contactJournals: (contactId: string, filters?: ContactJournalsFilters) =>
    [...journalKeys.all, 'contact', contactId, filters] as const,
};

// Contact Journals Filters
export interface ContactJournalsFilters {
  relationship_type?: string;
  page?: number;
  limit?: number;
}

export const journalTagKeys = {
  all: ['journal-tags'] as const,
  lists: () => [...journalTagKeys.all, 'list'] as const,
};

export const journalSeriesKeys = {
  all: ['journal-series'] as const,
  lists: () => [...journalSeriesKeys.all, 'list'] as const,
  details: () => [...journalSeriesKeys.all, 'detail'] as const,
  detail: (id: string) => [...journalSeriesKeys.details(), id] as const,
};

export const calendarKeys = {
  all: ['calendars'] as const,
  lists: () => [...calendarKeys.all, 'list'] as const,
};

// API Functions
async function fetchJournals(
  filters: JournalFilters = {}
): Promise<JournalListResponse> {
  const params = new URLSearchParams();

  if (filters.search) params.append('search', filters.search);
  // Backend expects 'type' (singular) for filtering by a single journal type
  if (filters.types && filters.types.length > 0) {
    // For now, only send the first type since backend expects singular
    params.append('type', filters.types[0]);
  }
  if (filters.contact_id) params.append('contact_id', filters.contact_id);
  // Backend accepts a repeatable 'tag_ids' param and expands each tag to its
  // descendants, so every selected tag is sent.
  if (filters.tag_ids && filters.tag_ids.length > 0) {
    for (const tagId of filters.tag_ids) {
      params.append('tag_ids', tagId);
    }
  }
  if (filters.calendar_id) params.append('calendar_id', filters.calendar_id);
  if (filters.parent_id !== undefined && filters.parent_id !== null) {
    params.append('parent_id', filters.parent_id.toString());
  }
  // Backend expects 'start_date' and 'end_date'
  if (filters.date_from) params.append('start_date', filters.date_from);
  if (filters.date_to) params.append('end_date', filters.date_to);
  if (filters.page) params.append('page', filters.page.toString());
  if (filters.limit) params.append('limit', filters.limit.toString());

  const url = params.toString()
    ? `${API_ENDPOINTS.JOURNALS.BASE}?${params.toString()}`
    : API_ENDPOINTS.JOURNALS.BASE;

  const response = await fetch(url, {
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.FETCH_FAILED
    );
  }

  return response.json();
}

async function fetchJournal(id: string): Promise<JournalResponse> {
  const response = await fetch(API_ENDPOINTS.JOURNALS.BY_ID(id), {
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.FETCH_FAILED
    );
  }

  return response.json();
}

async function searchJournals(
  query: string,
  options: {
    page?: number;
    limit?: number;
    types?: JournalType[];
  } = {}
): Promise<JournalListResponse> {
  const params = new URLSearchParams();
  params.append('q', query);

  if (options.page) params.append('page', options.page.toString());
  if (options.limit) params.append('limit', options.limit.toString());
  if (options.types) {
    options.types.forEach(type => params.append('types', type));
  }

  const response = await fetch(
    `${API_ENDPOINTS.JOURNALS.SEARCH}?${params.toString()}`,
    {
      credentials: 'include',
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.SEARCH_FAILED
    );
  }

  return response.json();
}

async function fetchContactJournals(
  contactId: string,
  filters: ContactJournalsFilters = {}
): Promise<JournalListResponse> {
  const params = new URLSearchParams();
  params.append('page', (filters.page || 1).toString());
  params.append('limit', (filters.limit || 20).toString());
  if (filters.relationship_type) {
    params.append('relationship_type', filters.relationship_type);
  }

  const response = await fetch(
    `/api/contacts/${contactId}/journals?${params.toString()}`,
    {
      credentials: 'include',
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.FETCH_FAILED
    );
  }

  return response.json();
}

async function createJournal(data: JournalFormData): Promise<JournalResponse> {
  const requestData = {
    type: 'journals' as const,
    attributes: data,
  };

  const response = await fetch(API_ENDPOINTS.JOURNALS.BASE, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ data: requestData }),
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.CREATE_FAILED
    );
  }

  return response.json();
}

async function updateJournal(
  id: string,
  data: Partial<JournalFormData>
): Promise<JournalResponse> {
  const requestData = {
    type: 'journals' as const,
    id,
    attributes: data,
  };

  const response = await fetch(API_ENDPOINTS.JOURNALS.BY_ID(id), {
    method: 'PATCH',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ data: requestData }),
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.UPDATE_FAILED
    );
  }

  return response.json();
}

async function deleteJournal(id: string): Promise<void> {
  const response = await fetch(API_ENDPOINTS.JOURNALS.BY_ID(id), {
    method: 'DELETE',
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.DELETE_FAILED
    );
  }
}

async function mergeJournal(
  targetId: string,
  sourceId: string,
  overrides?: MergeOverrides
): Promise<JournalResponse> {
  const requestData = {
    type: 'journal-merge' as const,
    attributes: {
      source_journal_id: Number(sourceId),
      ...(overrides ? { overrides } : {}),
    },
  };

  const response = await fetch(
    `${API_ENDPOINTS.JOURNALS.BY_ID(targetId)}/merge`,
    {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ data: requestData }),
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.UPDATE_FAILED
    );
  }

  return response.json();
}

async function updateJournalField(
  journalId: string,
  fieldName: string,
  value: unknown
): Promise<JournalResponse> {
  const requestData = {
    type: 'journal_fields' as const,
    attributes: { value },
  };

  const response = await fetch(
    `${API_ENDPOINTS.JOURNALS.BY_ID(journalId)}/fields/${fieldName}`,
    {
      method: 'PATCH',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ data: requestData }),
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.UPDATE_FAILED
    );
  }

  return response.json();
}

// Type Management Functions
async function addJournalType(
  journalId: string,
  journalType: JournalType,
  typeData?: Record<string, unknown>
): Promise<JournalResponse> {
  const requestData = {
    type: 'journal-types' as const,
    attributes: {
      journal_type: journalType,
      type_data: typeData || {},
    },
  };

  const response = await fetch(
    `${API_ENDPOINTS.JOURNALS.BY_ID(journalId)}/types`,
    {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ data: requestData }),
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.CREATE_FAILED
    );
  }

  return response.json();
}

async function removeJournalType(
  journalId: string,
  journalType: JournalType
): Promise<JournalResponse> {
  const response = await fetch(
    `${API_ENDPOINTS.JOURNALS.BY_ID(journalId)}/types/${journalType}`,
    {
      method: 'DELETE',
      credentials: 'include',
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.DELETE_FAILED
    );
  }

  return response.json();
}

async function updateTypeData(
  journalId: string,
  journalType: JournalType,
  typeData: Record<string, unknown>
): Promise<JournalResponse> {
  const requestData = {
    type: 'journal-type-data' as const,
    attributes: typeData,
  };

  const response = await fetch(
    `${API_ENDPOINTS.JOURNALS.BY_ID(journalId)}/types/${journalType}/data`,
    {
      method: 'PUT',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ data: requestData }),
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.UPDATE_FAILED
    );
  }

  return response.json();
}

// Contact Relationship Management Functions
async function addContactRelationship(
  journalId: string,
  contactId: string,
  relationshipType: JournalContactRelationshipType,
  status?: AttendeeStatus | null,
  role?: ContactEventRole | null
): Promise<JournalResponse> {
  const requestData = {
    type: 'journal-contact-relationships' as const,
    attributes: {
      contact_id: contactId,
      relationship_type: relationshipType,
      ...(status !== undefined && { status }),
      ...(role !== undefined && { role }),
    },
  };

  const response = await fetch(
    `${API_ENDPOINTS.JOURNALS.BY_ID(journalId)}/relationships/contacts`,
    {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ data: requestData }),
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.CREATE_FAILED
    );
  }

  return response.json();
}

async function removeContactRelationship(
  journalId: string,
  contactId: string,
  relationshipType: JournalContactRelationshipType
): Promise<JournalResponse> {
  const response = await fetch(
    `${API_ENDPOINTS.JOURNALS.BY_ID(journalId)}/relationships/contacts/${contactId}/${relationshipType}`,
    {
      method: 'DELETE',
      credentials: 'include',
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.DELETE_FAILED
    );
  }

  return response.json();
}

async function updateContactRelationship(
  journalId: string,
  contactId: string,
  relationshipType: JournalContactRelationshipType,
  status?: AttendeeStatus | null,
  role?: ContactEventRole | null
): Promise<JournalResponse> {
  const requestData = {
    type: 'journal-contact-relationships' as const,
    attributes: {
      ...(status !== undefined && { status }),
      ...(role !== undefined && { role }),
    },
  };

  const response = await fetch(
    `${API_ENDPOINTS.JOURNALS.BY_ID(journalId)}/relationships/contacts/${contactId}/${relationshipType}`,
    {
      method: 'PATCH',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ data: requestData }),
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.UPDATE_FAILED
    );
  }

  return response.json();
}

// Tag Management Functions
async function addJournalTag(
  journalId: string,
  tagId: string
): Promise<JournalResponse> {
  const requestData = {
    type: 'journal-tag' as const, // Backend expects singular 'journal-tag'
    attributes: {
      tag_id: tagId,
    },
  };

  const response = await fetch(
    `${API_ENDPOINTS.JOURNALS.BY_ID(journalId)}/relationships/tags`,
    {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ data: requestData }),
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.CREATE_FAILED
    );
  }

  return response.json();
}

async function removeJournalTag(
  journalId: string,
  tagId: string
): Promise<JournalResponse> {
  const response = await fetch(
    `${API_ENDPOINTS.JOURNALS.BY_ID(journalId)}/relationships/tags/${tagId}`,
    {
      method: 'DELETE',
      credentials: 'include',
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.DELETE_FAILED
    );
  }

  return response.json();
}

// Fetch available journal tags
async function fetchJournalTags(): Promise<{ data: JournalTag[] }> {
  const response = await fetch('/api/journals/tags', {
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.FETCH_FAILED
    );
  }

  const jsonApiResponse: {
    data: Array<{
      id: string;
      type: string;
      attributes: {
        name: string;
        color?: string | null;
        description?: string | null;
        parent_id?: string | null;
      };
    }>;
  } = await response.json();

  // Transform JSON:API format to flat JournalTag objects
  const tags: JournalTag[] = jsonApiResponse.data.map(resource => ({
    id: resource.id,
    name: resource.attributes.name,
    color: resource.attributes.color,
    description: resource.attributes.description ?? null,
    parent_id: resource.attributes.parent_id ?? null,
  }));

  return { data: tags };
}

// Attributes accepted when creating a journal tag.
export interface JournalTagCreateAttributes {
  name: string;
  color?: string;
  description?: string;
  parent_id?: string;
}

/**
 * Attributes accepted when updating a journal tag.
 *
 * Every field is optional — omitted attributes are left unchanged by the
 * backend. An explicit `null` `parent_id` is the wire signal for "move this tag
 * back to the root of the hierarchy".
 */
export interface JournalTagUpdateAttributes {
  name?: string;
  color?: string;
  description?: string;
  parent_id?: string | null;
}

// Update an existing journal tag and return the updated JSON:API resource.
async function updateJournalTag(
  id: string,
  attributes: JournalTagUpdateAttributes
): Promise<{ data: { id: string } }> {
  const response = await fetch(`/api/journals/tags/${id}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      data: {
        type: 'journal-tags',
        id,
        attributes,
      },
    }),
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.UPDATE_FAILED
    );
  }

  return response.json();
}

/**
 * Delete a journal tag.
 *
 * The tag is removed from every journal it is assigned to rather than the
 * request being refused, and the tag's children are re-parented to the root —
 * the backend owns both, so there is nothing to reconcile here.
 */
async function deleteJournalTag(id: string): Promise<void> {
  const response = await fetch(`/api/journals/tags/${id}`, {
    method: 'DELETE',
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.DELETE_FAILED
    );
  }
}

/**
 * Merge one journal tag into another, deleting the source.
 *
 * The source is the path parameter and the target travels in the body, matching
 * the endpoint's JSON:API shape. The resource type is part of the contract: the
 * controller rejects anything other than `journal-tags` with a 400.
 */
async function mergeJournalTag(
  sourceId: string,
  targetId: string
): Promise<void> {
  const response = await fetch(`/api/journals/tags/${sourceId}/merge`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      data: {
        type: 'journal-tags',
        attributes: {
          target_tag_id: targetId,
        },
      },
    }),
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(errorData.errors?.[0]?.detail || 'Failed to merge tag');
  }
}

// Create a new journal tag and return the created JSON:API resource.
async function createJournalTag(
  attributes: JournalTagCreateAttributes
): Promise<{ data: { id: string } }> {
  const response = await fetch('/api/journals/tags', {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      data: {
        type: 'journal-tags',
        attributes,
      },
    }),
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.CREATE_FAILED
    );
  }

  return response.json();
}

// Fetch available calendars
async function fetchCalendars(): Promise<{
  data: Array<{
    id: string;
    attributes: {
      name: string;
      color: string | null;
      description?: string | null;
      is_synced_to_google?: boolean;
      google_calendar_id?: string | null;
    };
  }>;
}> {
  const response = await fetch('/api/calendars', {
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.FETCH_FAILED
    );
  }

  return response.json();
}

async function createCalendar(
  data: Omit<JournalCalendar, 'id'>
): Promise<{ data: { id: string; attributes: Omit<JournalCalendar, 'id'> } }> {
  const requestData = {
    type: 'calendars' as const,
    attributes: data,
  };

  const response = await fetch('/api/calendars', {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ data: requestData }),
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.CREATE_FAILED
    );
  }

  return response.json();
}

async function updateCalendar(
  id: string,
  data: Partial<Omit<JournalCalendar, 'id'>>
): Promise<{ data: { id: string; attributes: Omit<JournalCalendar, 'id'> } }> {
  const requestData = {
    type: 'calendars' as const,
    id,
    attributes: data,
  };

  const response = await fetch(`/api/calendars/${id}`, {
    method: 'PUT',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ data: requestData }),
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.UPDATE_FAILED
    );
  }

  return response.json();
}

async function deleteCalendar(id: string): Promise<void> {
  const response = await fetch(`/api/calendars/${id}`, {
    method: 'DELETE',
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.DELETE_FAILED
    );
  }
}

interface JournalPaginationMeta {
  totalCount?: number;
  currentPage?: number;
  pageCount?: number;
  perPage?: number;
}

function getMetaNumber(
  meta: JsonApiMeta | undefined,
  ...keys: string[]
): number | undefined {
  if (!meta) return undefined;
  for (const key of keys) {
    const value = meta[key];
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value;
    }
  }
  return undefined;
}

export function getJournalPaginationMeta(
  meta?: JsonApiMeta
): JournalPaginationMeta {
  return {
    totalCount: getMetaNumber(meta, 'total_count', 'total'),
    currentPage: getMetaNumber(meta, 'current_page', 'page'),
    pageCount: getMetaNumber(meta, 'page_count', 'total_pages', 'totalPages'),
    perPage: getMetaNumber(meta, 'per_page', 'limit'),
  };
}

export function getNextJournalPageParam(
  lastPage: JournalListResponse
): number | undefined {
  const { currentPage, pageCount } = getJournalPaginationMeta(lastPage.meta);
  if (
    currentPage === undefined ||
    pageCount === undefined ||
    currentPage >= pageCount
  ) {
    return undefined;
  }
  return currentPage + 1;
}

function omitPage<T extends { page?: number }>(value: T): Omit<T, 'page'> {
  const nextValue = { ...value };
  delete nextValue.page;
  return nextValue as Omit<T, 'page'>;
}

function getListQueryFilters(filters: JournalFilters): JournalFilters {
  return omitPage(filters);
}

// React Query Hooks
export function useJournals(
  filters: JournalFilters = {},
  options: { enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: journalKeys.list(filters),
    queryFn: () => fetchJournals(filters),
    staleTime: 5 * 60 * 1000, // 5 minutes
    enabled: options.enabled,
  });
}

export function useDailySummary(
  date: string,
  options: { enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: [...journalKeys.all, 'daily-summary', date],
    queryFn: async (): Promise<DailySummaryResponse> => {
      const response = await fetch(`/api/journals/daily-summary/${date}`, {
        credentials: 'include',
      });
      if (!response.ok) {
        const errorData: JsonApiErrorResponse = await response.json();
        throw new Error(
          errorData.errors?.[0]?.detail || 'Failed to load daily summary'
        );
      }
      return response.json();
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
    enabled: (options.enabled ?? true) && Boolean(date),
  });
}

export function useRegenerateDailySummary() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (date: string): Promise<DailySummaryResponse> => {
      const response = await fetch(
        `/api/journals/daily-summary/${date}/regenerate`,
        {
          method: 'POST',
          credentials: 'include',
        }
      );
      if (!response.ok) {
        const errorData: JsonApiErrorResponse = await response.json();
        throw new Error(
          errorData.errors?.[0]?.detail || 'Failed to regenerate daily summary'
        );
      }
      return response.json();
    },
    onSuccess: (data, date) => {
      queryClient.setQueryData(
        [...journalKeys.all, 'daily-summary', date],
        data
      );
      if (data.data) {
        toast.success('Daily summary regenerated successfully');
      } else {
        toast.info(
          'Summary generation is not available. Check AI configuration.'
        );
      }
    },
    onError: error => {
      toast.error(error.message || 'Failed to regenerate daily summary');
    },
  });
}

export interface DateChunkPageParam {
  date_from: string;
  date_to: string;
}

export function useInfiniteJournals(
  filters: JournalFilters = {},
  options: { enabled?: boolean; chunkDays?: number; anchorDate?: string } = {}
) {
  const { chunkDays = 7 } = options;
  const anchor = options.anchorDate ? parseISO(options.anchorDate) : new Date();

  // When the user has applied an explicit date-range filter, honour it instead
  // of the chunk-based window so that the filter actually works.
  const hasUserDateFilter = Boolean(filters.date_from || filters.date_to);

  // Calculate initial boundary around anchor date
  // (e.g. for chunkDays=7, it fetches anchor - 3 days to anchor + 3 days)
  const halfChunk = Math.floor(chunkDays / 2);
  const initialStartDate = format(subDays(anchor, halfChunk), 'yyyy-MM-dd');
  const initialEndDate = format(
    addDays(anchor, chunkDays - 1 - halfChunk),
    'yyyy-MM-dd'
  );

  const initialPageParam: DateChunkPageParam = {
    date_from: filters.date_from ?? initialStartDate,
    date_to: filters.date_to ?? initialEndDate,
  };

  return useInfiniteQuery({
    queryKey: journalKeys.infiniteList(getListQueryFilters(filters), {
      chunkDays: options.chunkDays,
      anchorDate: options.anchorDate,
    }),
    queryFn: ({ pageParam }) =>
      fetchJournals({
        ...filters,
        date_from: filters.date_from ?? pageParam.date_from,
        date_to: filters.date_to ?? pageParam.date_to,
        // The API safely supports up to limit=100. 100 is chosen as the max permissible value to cover dense 7-day chunks
        // without risking dropped items or invoking REST offsets over chunk edges.
        limit: 100,
        page: undefined, // Skip internal REST offset pagination
      }),
    initialPageParam,
    getNextPageParam: (lastPage, allPages, lastPageParam) => {
      // When the user has an explicit date filter, don't paginate further
      if (hasUserDateFilter) return undefined;
      try {
        // Progressing into the FUTURE (Scrolling DOWN)
        const prevEnd = parseISO(lastPageParam.date_to);
        const newStart = addDays(prevEnd, 1);
        const newEnd = addDays(newStart, chunkDays - 1);
        return {
          date_from: format(newStart, 'yyyy-MM-dd'),
          date_to: format(newEnd, 'yyyy-MM-dd'),
        };
      } catch {
        return undefined;
      }
    },
    getPreviousPageParam: (firstPage, allPages, firstPageParam) => {
      // When the user has an explicit date filter, don't paginate further
      if (hasUserDateFilter) return undefined;
      try {
        // Progressing into the PAST (Scrolling UP)
        const prevEnd = parseISO(firstPageParam.date_from);
        const newEnd = subDays(prevEnd, 1);
        const newStart = subDays(newEnd, chunkDays - 1);
        return {
          date_from: format(newStart, 'yyyy-MM-dd'),
          date_to: format(newEnd, 'yyyy-MM-dd'),
        };
      } catch {
        return undefined;
      }
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
    enabled: options.enabled,
  });
}

export function useJournal(id: string) {
  return useQuery({
    queryKey: journalKeys.detail(id),
    queryFn: () => fetchJournal(id),
    enabled: !!id,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

export function useSearchJournals(
  query: string,
  options: {
    page?: number;
    limit?: number;
    types?: JournalType[];
  } = {},
  queryOptions: { enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: journalKeys.search(`${query}-${JSON.stringify(options)}`),
    queryFn: () => searchJournals(query, options),
    enabled: queryOptions.enabled ?? query.length > 0,
    staleTime: 2 * 60 * 1000, // 2 minutes for search results
  });
}

export function useJournalTags() {
  return useQuery({
    queryKey: journalTagKeys.lists(),
    queryFn: fetchJournalTags,
    staleTime: 10 * 60 * 1000, // 10 minutes
  });
}

export function useCreateJournalTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (attributes: JournalTagCreateAttributes) =>
      createJournalTag(attributes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: journalTagKeys.lists() });
      // The tag tree, the journals list and any open journal's tag editor all
      // read the tag namespace; refresh the journal queries alongside it.
      queryClient.invalidateQueries({ queryKey: journalKeys.all });
      toast.success('Tag created successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

/**
 * Updates a journal tag's name, colour, description or parent.
 *
 * A rename or recolour changes the chips rendered on the journals list and on
 * every open journal detail page, so both the tag namespace and the journal
 * queries are invalidated.
 */
export function useUpdateJournalTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      attributes,
    }: {
      id: string;
      attributes: JournalTagUpdateAttributes;
    }) => updateJournalTag(id, attributes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: journalTagKeys.lists() });
      queryClient.invalidateQueries({ queryKey: journalKeys.all });
      toast.success(SUCCESS_MESSAGES.TAG_UPDATED);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

/**
 * Refreshes everything a journal tag mutation can change.
 *
 * The tag namespace feeds the sidebar tree and the detail page's tag editor;
 * the journal queries feed the chips on the list and on any open journal. Both
 * are **cancelled before being invalidated**: a fetch that started before the
 * mutation would otherwise settle after it, writing pre-mutation rows into the
 * cache and marking them fresh — and with `staleTime` at five minutes for the
 * journals list and ten for the tag list, nothing would refetch again for that
 * long, leaving a deleted tag on screen.
 *
 * Unlike the contact equivalents this neither splices the cache by hand nor
 * delays the invalidation behind a timer: the write commits in the service
 * layer before the response is sent, so there is no read-after-write race to
 * wait out.
 */
async function refreshAfterJournalTagMutation(
  queryClient: ReturnType<typeof useQueryClient>
): Promise<void> {
  await Promise.all([
    queryClient.cancelQueries({ queryKey: journalTagKeys.lists() }),
    queryClient.cancelQueries({ queryKey: journalKeys.all }),
  ]);
  queryClient.invalidateQueries({ queryKey: journalTagKeys.lists() });
  queryClient.invalidateQueries({ queryKey: journalKeys.all });
}

/**
 * Deletes a journal tag, which also un-assigns it from every journal.
 */
export function useDeleteJournalTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => deleteJournalTag(id),
    onSuccess: async () => {
      await refreshAfterJournalTagMutation(queryClient);
      toast.success(SUCCESS_MESSAGES.TAG_DELETED);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

/**
 * Merges a journal tag into another, deleting the source tag.
 *
 * Journals tagged with the source end up tagged with the target, so the journal
 * queries are invalidated alongside the tag namespace.
 */
export function useMergeJournalTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      sourceId,
      targetId,
    }: {
      sourceId: string;
      targetId: string;
    }) => mergeJournalTag(sourceId, targetId),
    onSuccess: async () => {
      await refreshAfterJournalTagMutation(queryClient);
      toast.success('Tag successfully merged');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useCalendars() {
  return useQuery({
    queryKey: calendarKeys.lists(),
    queryFn: fetchCalendars,
    staleTime: 10 * 60 * 1000, // 10 minutes
  });
}

export function useCreateCalendar() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createCalendar,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: calendarKeys.lists() });
      toast.success('Calendar created successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useUpdateCalendar() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: Partial<Omit<JournalCalendar, 'id'>>;
    }) => updateCalendar(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: calendarKeys.lists() });
      toast.success('Calendar updated successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useDeleteCalendar() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteCalendar,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: calendarKeys.lists() });
      toast.success('Calendar deleted successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useCreateJournal() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createJournal,
    onSuccess: () => {
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: journalKeys.all });
      }, 150);
      toast.success(SUCCESS_MESSAGES.JOURNAL_CREATED);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useUpdateJournal() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: Partial<JournalFormData>;
    }) => updateJournal(id, data),
    onSuccess: (_, { id }) => {
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: journalKeys.detail(id) });
        queryClient.invalidateQueries({ queryKey: journalKeys.lists() });
      }, 150);
      toast.success(SUCCESS_MESSAGES.JOURNAL_UPDATED);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useDeleteJournal() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteJournal,
    onSuccess: () => {
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: journalKeys.lists() });
      }, 150);
      toast.success(SUCCESS_MESSAGES.JOURNAL_DELETED);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useMergeJournal() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      targetId,
      sourceId,
      overrides,
    }: {
      targetId: string;
      sourceId: string;
      overrides?: MergeOverrides;
    }) => mergeJournal(targetId, sourceId, overrides),
    onSuccess: (_, { targetId, sourceId }) => {
      queryClient.invalidateQueries({ queryKey: journalKeys.detail(targetId) });
      queryClient.invalidateQueries({ queryKey: journalKeys.detail(sourceId) });
      queryClient.invalidateQueries({ queryKey: journalKeys.lists() });
      queryClient.invalidateQueries({ queryKey: reviewItemKeys.all });
      toast.success('Journals merged successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useUpdateJournalField() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      journalId,
      fieldName,
      value,
    }: {
      journalId: string;
      fieldName: string;
      value: unknown;
    }) => updateJournalField(journalId, fieldName, value),
    onSuccess: (data, variables) => {
      const journalId = variables.journalId;
      queryClient.invalidateQueries({
        queryKey: journalKeys.detail(journalId),
      });
      queryClient.invalidateQueries({ queryKey: journalKeys.lists() });
    },
    onError: (error: Error) => {
      // Don't show toast here - let the component handle it
      console.error('Field update failed:', error);
    },
  });
}

export function useAddJournalType() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      journalId,
      journalType,
      typeData,
    }: {
      journalId: string;
      journalType: JournalType;
      typeData?: Record<string, unknown>;
    }) => addJournalType(journalId, journalType, typeData),
    onSuccess: (_, { journalId }) => {
      queryClient.invalidateQueries({
        queryKey: journalKeys.detail(journalId),
      });
      queryClient.invalidateQueries({ queryKey: journalKeys.lists() });
      toast.success('Journal type added successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useRemoveJournalType() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      journalId,
      journalType,
    }: {
      journalId: string;
      journalType: JournalType;
    }) => removeJournalType(journalId, journalType),
    onSuccess: (_, { journalId }) => {
      queryClient.invalidateQueries({
        queryKey: journalKeys.detail(journalId),
      });
      queryClient.invalidateQueries({ queryKey: journalKeys.lists() });
      toast.success('Journal type removed successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useUpdateTypeData() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      journalId,
      journalType,
      typeData,
    }: {
      journalId: string;
      journalType: JournalType;
      typeData: Record<string, unknown>;
    }) => updateTypeData(journalId, journalType, typeData),
    onSuccess: (_, { journalId }) => {
      queryClient.invalidateQueries({
        queryKey: journalKeys.detail(journalId),
      });
      queryClient.invalidateQueries({ queryKey: journalKeys.lists() });
      toast.success('Type data updated successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useAddContactRelationship() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      journalId,
      contactId,
      relationshipType,
      status,
      role,
    }: {
      journalId: string;
      contactId: string;
      relationshipType: JournalContactRelationshipType;
      status?: AttendeeStatus | null;
      role?: ContactEventRole | null;
    }) =>
      addContactRelationship(
        journalId,
        contactId,
        relationshipType,
        status,
        role
      ),
    onSuccess: (_, { journalId }) => {
      queryClient.invalidateQueries({
        queryKey: journalKeys.detail(journalId),
      });
      queryClient.invalidateQueries({ queryKey: journalKeys.lists() });
      toast.success('Contact relationship added successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useRemoveContactRelationship() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      journalId,
      contactId,
      relationshipType,
    }: {
      journalId: string;
      contactId: string;
      relationshipType: JournalContactRelationshipType;
    }) => removeContactRelationship(journalId, contactId, relationshipType),
    onSuccess: (_, { journalId }) => {
      queryClient.invalidateQueries({
        queryKey: journalKeys.detail(journalId),
      });
      queryClient.invalidateQueries({ queryKey: journalKeys.lists() });
      toast.success('Contact relationship removed successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useUpdateContactRelationship() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      journalId,
      contactId,
      relationshipType,
      status,
      role,
    }: {
      journalId: string;
      contactId: string;
      relationshipType: JournalContactRelationshipType;
      status?: AttendeeStatus | null;
      role?: ContactEventRole | null;
    }) =>
      updateContactRelationship(
        journalId,
        contactId,
        relationshipType,
        status,
        role
      ),
    onSuccess: (_, { journalId }) => {
      queryClient.invalidateQueries({
        queryKey: journalKeys.detail(journalId),
      });
      queryClient.invalidateQueries({ queryKey: journalKeys.lists() });
      toast.success('Contact relationship updated successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useAddJournalTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ journalId, tagId }: { journalId: string; tagId: string }) =>
      addJournalTag(journalId, tagId),
    onSuccess: (_, { journalId }) => {
      queryClient.invalidateQueries({
        queryKey: journalKeys.detail(journalId),
      });
      queryClient.invalidateQueries({ queryKey: journalKeys.lists() });
      toast.success('Tag added successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useRemoveJournalTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ journalId, tagId }: { journalId: string; tagId: string }) =>
      removeJournalTag(journalId, tagId),
    onSuccess: (_, { journalId }) => {
      queryClient.invalidateQueries({
        queryKey: journalKeys.detail(journalId),
      });
      queryClient.invalidateQueries({ queryKey: journalKeys.lists() });
      toast.success('Tag removed successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

// ── Journal Series ────────────────────────────────────────────────────

export interface JournalSeriesMemberJournal {
  id: number;
  title: string;
  event_date_range_start?: string | null;
}

export interface JournalSeriesDetail extends JournalSeries {
  member_journals: JournalSeriesMemberJournal[];
}

interface JournalSeriesResourceJson {
  id: string;
  type: string;
  attributes: {
    name: string;
    description?: string | null;
    auto_created?: boolean;
    member_journals?: JournalSeriesMemberJournal[];
  };
}

function toJournalSeries(resource: JournalSeriesResourceJson): JournalSeries {
  return {
    id: resource.id,
    name: resource.attributes.name,
    description: resource.attributes.description,
    auto_created: resource.attributes.auto_created,
  };
}

async function fetchJournalSeriesList(): Promise<{ data: JournalSeries[] }> {
  const response = await fetch('/api/journals/series', {
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.FETCH_FAILED
    );
  }

  const jsonApiResponse: { data: JournalSeriesResourceJson[] } =
    await response.json();
  return { data: jsonApiResponse.data.map(toJournalSeries) };
}

async function fetchJournalSeriesDetail(
  seriesId: string
): Promise<JournalSeriesDetail> {
  const response = await fetch(`/api/journals/series/${seriesId}`, {
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.FETCH_FAILED
    );
  }

  const jsonApiResponse: { data: JournalSeriesResourceJson } =
    await response.json();
  return {
    ...toJournalSeries(jsonApiResponse.data),
    member_journals: jsonApiResponse.data.attributes.member_journals ?? [],
  };
}

async function createJournalSeries(data: {
  name: string;
  description?: string | null;
}): Promise<JournalSeries> {
  const response = await fetch('/api/journals/series', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      data: {
        type: 'journal-series',
        attributes: { name: data.name, description: data.description ?? null },
      },
    }),
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.CREATE_FAILED
    );
  }

  const jsonApiResponse: { data: JournalSeriesResourceJson } =
    await response.json();
  return toJournalSeries(jsonApiResponse.data);
}

async function deleteJournalSeries(seriesId: string): Promise<void> {
  const response = await fetch(`/api/journals/series/${seriesId}`, {
    method: 'DELETE',
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.DELETE_FAILED
    );
  }
}

async function addJournalToSeries(
  journalId: string,
  seriesId: string
): Promise<void> {
  const response = await fetch(
    `/api/journals/${journalId}/relationships/series`,
    {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        data: { type: 'journal-series', id: seriesId },
      }),
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.UPDATE_FAILED
    );
  }
}

async function removeJournalFromSeries(
  journalId: string,
  seriesId: string
): Promise<void> {
  const response = await fetch(
    `/api/journals/${journalId}/relationships/series/${seriesId}`,
    {
      method: 'DELETE',
      credentials: 'include',
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.UPDATE_FAILED
    );
  }
}

export function useJournalSeries() {
  return useQuery({
    queryKey: journalSeriesKeys.lists(),
    queryFn: fetchJournalSeriesList,
    staleTime: 10 * 60 * 1000, // 10 minutes
  });
}

export function useJournalSeriesDetail(seriesId: string) {
  return useQuery({
    queryKey: journalSeriesKeys.detail(seriesId),
    queryFn: () => fetchJournalSeriesDetail(seriesId),
    enabled: !!seriesId,
  });
}

export function useCreateJournalSeries() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createJournalSeries,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: journalSeriesKeys.lists() });
      toast.success('Series created successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useDeleteJournalSeries() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteJournalSeries,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: journalSeriesKeys.all });
      queryClient.invalidateQueries({ queryKey: journalKeys.details() });
      toast.success('Series deleted successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useAddJournalToSeries() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      journalId,
      seriesId,
    }: {
      journalId: string;
      seriesId: string;
    }) => addJournalToSeries(journalId, seriesId),
    onSuccess: (_, { journalId, seriesId }) => {
      queryClient.invalidateQueries({
        queryKey: journalKeys.detail(journalId),
      });
      queryClient.invalidateQueries({
        queryKey: journalSeriesKeys.detail(seriesId),
      });
      toast.success('Added to series');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useRemoveJournalFromSeries() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      journalId,
      seriesId,
    }: {
      journalId: string;
      seriesId: string;
    }) => removeJournalFromSeries(journalId, seriesId),
    onSuccess: (_, { journalId, seriesId }) => {
      queryClient.invalidateQueries({
        queryKey: journalKeys.detail(journalId),
      });
      queryClient.invalidateQueries({
        queryKey: journalSeriesKeys.detail(seriesId),
      });
      toast.success('Removed from series');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useContactJournals(
  contactId: string,
  filters: ContactJournalsFilters = {}
) {
  return useQuery({
    queryKey: journalKeys.contactJournals(contactId, filters),
    queryFn: () => fetchContactJournals(contactId, filters),
    enabled: !!contactId,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

// Review Queue

export const reviewItemKeys = {
  all: ['review-items'] as const,
  lists: () => [...reviewItemKeys.all, 'list'] as const,
  list: (status: string, page: number, limit: number) =>
    [...reviewItemKeys.lists(), { status, page, limit }] as const,
};

/**
 * Get pending review items queue
 */
export async function getReviewItems(
  status = 'pending',
  page = 1,
  limit = 20
): Promise<ReviewItemsListResponse> {
  const params = new URLSearchParams({
    status,
    page: page.toString(),
    limit: limit.toString(),
  });

  const response = await fetch(
    `/api/journals/review-items?${params.toString()}`,
    {
      credentials: 'include',
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response
      .json()
      .catch(() => ({}));
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.FETCH_FAILED
    );
  }

  return response.json();
}

export function useReviewItems(status = 'pending', page = 1, limit = 20) {
  return useQuery({
    queryKey: reviewItemKeys.list(status, page, limit),
    queryFn: () => getReviewItems(status, page, limit),
  });
}

/**
 * Dismiss a pending review item
 */
export async function dismissReviewItem(id: string): Promise<unknown> {
  const response = await fetch(`/api/journals/review-items/${id}/dismiss`, {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response
      .json()
      .catch(() => ({}));
    throw new Error(
      errorData.errors?.[0]?.detail || 'Failed to dismiss review item'
    );
  }

  return response.json();
}

/**
 * Hook to dismiss a review item
 */
export function useDismissReviewItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: dismissReviewItem,
    // Optimistically drop the dismissed item from every cached review-items
    // list so the sidebar updates immediately. The backend commits the dismiss
    // at request teardown, so the invalidation-triggered refetch can otherwise
    // still return the item (read-after-write) and leave it on screen.
    onMutate: async (id: string) => {
      await queryClient.cancelQueries({ queryKey: reviewItemKeys.lists() });
      const previousLists = queryClient.getQueriesData<ReviewItemsListResponse>(
        {
          queryKey: reviewItemKeys.lists(),
        }
      );
      queryClient.setQueriesData<ReviewItemsListResponse>(
        { queryKey: reviewItemKeys.lists() },
        old =>
          old ? { ...old, data: old.data.filter(item => item.id !== id) } : old
      );
      return { previousLists };
    },
    onError: (error: Error, _id, context) => {
      context?.previousLists?.forEach(([key, data]) => {
        queryClient.setQueryData(key, data);
      });
      toast.error(error.message);
    },
    onSuccess: () => {
      toast.success('Review item dismissed');
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: reviewItemKeys.all });
      queryClient.invalidateQueries({ queryKey: journalKeys.lists() });
      queryClient.invalidateQueries({ queryKey: journalKeys.details() });
    },
  });
}

/**
 * Auto-merge all pending review items that have no conflicts
 */
export async function autoMergeReviewItems(): Promise<AutoMergeResponse> {
  const response = await fetch('/api/journals/review-items/auto-merge', {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response
      .json()
      .catch(() => ({}));
    throw new Error(
      errorData.errors?.[0]?.detail || 'Failed to auto-merge review items'
    );
  }

  return response.json();
}

/**
 * Hook to auto-merge all non-conflicting review items
 */
export function useAutoMergeReviewItems() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: autoMergeReviewItems,
    onSuccess: data => {
      const { merged_count, errors } = data.data.attributes;
      queryClient.invalidateQueries({ queryKey: reviewItemKeys.all });
      queryClient.invalidateQueries({ queryKey: journalKeys.lists() });
      queryClient.invalidateQueries({ queryKey: journalKeys.details() });
      if (merged_count > 0) {
        toast.success(
          `Auto-merged ${merged_count} journal${merged_count === 1 ? '' : 's'} successfully`
        );
        if (errors && errors.length > 0) {
          toast.warning(
            `Some items failed to merge: ${errors.length} error(s)`
          );
        }
      } else if (errors && errors.length > 0) {
        toast.error(`Auto-merge failed: ${errors[0]}`);
      } else {
        toast.info(
          'No journals could be auto-merged (remaining items skipped)'
        );
      }
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

// ─── Outdoor Logbook Export ─────────────────────────────────────────

export interface LogbookExportFilters {
  start_date?: string;
  end_date?: string;
  activity_types?: string[];
}

async function exportOutdoorLogbook(
  filters: LogbookExportFilters = {}
): Promise<void> {
  const response = await fetch(API_ENDPOINTS.JOURNALS.EXPORT_OUTDOOR_LOGBOOK, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(filters),
  });

  if (!response.ok) {
    let errorMessage = 'Failed to generate logbook export';
    try {
      const errorData = await response.json();
      errorMessage = errorData.errors?.[0]?.detail || errorMessage;
    } catch {
      // Response body is not JSON, use default message
    }
    throw new Error(errorMessage);
  }

  // Trigger file download from the PDF blob
  const blob = await response.blob();
  const contentDisposition = response.headers.get('content-disposition');
  const filenameMatch = contentDisposition?.match(/filename="?([^"]+)"?/);
  const filename = filenameMatch?.[1] || 'outdoor_logbook.pdf';

  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 100);
}

/**
 * Hook to export outdoor logbook as PDF.
 */
export function useExportOutdoorLogbook() {
  return useMutation({
    mutationFn: exportOutdoorLogbook,
    onSuccess: () => {
      toast.success('Logbook exported successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

// Journal History API Functions
//
// Mirrors the contact history client (`lib/api/contacts.ts`) so the shared
// `ActivityFeed` can be driven by either entity. History is produced
// asynchronously by the projection consumer, so a just-made change may take a
// moment to appear — the 2-minute stale time matches the contact feed.
export const journalHistoryKeys = {
  all: ['journal-history'] as const,
  list: (journalId: string, page?: number, limit?: number) =>
    [...journalHistoryKeys.all, journalId, { page, limit }] as const,
};

export async function fetchJournalHistory(
  journalId: string,
  filters: HistoryFilters = {}
): Promise<HistoryListResponse> {
  const params = new URLSearchParams();

  if (filters.page) params.append('page', filters.page.toString());
  if (filters.limit) params.append('limit', filters.limit.toString());

  const url = `${API_ENDPOINTS.JOURNALS.BASE}/${journalId}/history?${params.toString()}`;

  const response = await fetch(url, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.FETCH_FAILED
    );
  }

  return response.json();
}

export function useJournalHistory(
  journalId: string,
  filters: HistoryFilters = {},
  options: { enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: journalHistoryKeys.list(journalId, filters.page, filters.limit),
    queryFn: () =>
      fetchJournalHistory(journalId, {
        page: filters.page,
        limit: filters.limit,
      }),
    enabled: options.enabled !== false && !!journalId,
    staleTime: 2 * 60 * 1000, // 2 minutes for history
  });
}
