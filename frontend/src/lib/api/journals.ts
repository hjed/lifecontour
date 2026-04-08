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
  JournalCalendar,
  MergeOverrides,
} from '@/types/journals';
import { JsonApiErrorResponse, JsonApiMeta } from '@/types/api';
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
  // Backend expects 'tag_id' (singular) for filtering by a single tag
  if (filters.tag_ids && filters.tag_ids.length > 0) {
    // For now, only send the first tag since backend expects singular
    params.append('tag_id', filters.tag_ids[0]);
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
  relationshipType: JournalContactRelationshipType
): Promise<JournalResponse> {
  const requestData = {
    type: 'journal-contact-relationships' as const,
    attributes: {
      contact_id: contactId,
      relationship_type: relationshipType,
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
        parent_id?: string | null;
      };
    }>;
  } = await response.json();

  // Transform JSON:API format to flat JournalTag objects
  const tags: JournalTag[] = jsonApiResponse.data.map(resource => ({
    id: resource.id,
    name: resource.attributes.name,
    color: resource.attributes.color,
  }));

  return { data: tags };
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

  // Calculate initial boundary around anchor date
  // (e.g. for chunkDays=7, it fetches anchor - 3 days to anchor + 3 days)
  const halfChunk = Math.floor(chunkDays / 2);
  const initialStartDate = format(subDays(anchor, halfChunk), 'yyyy-MM-dd');
  const initialEndDate = format(
    addDays(anchor, chunkDays - 1 - halfChunk),
    'yyyy-MM-dd'
  );

  const initialPageParam: DateChunkPageParam = {
    date_from: initialStartDate,
    date_to: initialEndDate,
  };

  return useInfiniteQuery({
    queryKey: journalKeys.infiniteList(getListQueryFilters(filters), {
      chunkDays: options.chunkDays,
      anchorDate: options.anchorDate,
    }),
    queryFn: ({ pageParam }) =>
      fetchJournals({
        ...filters,
        date_from: pageParam.date_from,
        date_to: pageParam.date_to,
        // The API safely supports up to limit=100. 100 is chosen as the max permissible value to cover dense 7-day chunks
        // without risking dropped items or invoking REST offsets over chunk edges.
        limit: 100,
        page: undefined, // Skip internal REST offset pagination
      }),
    initialPageParam,
    getNextPageParam: (lastPage, allPages, lastPageParam) => {
      try {
        // Progressing into the PAST (Scrolling DOWN)
        const prevEnd = parseISO(lastPageParam.date_from);
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
    getPreviousPageParam: (firstPage, allPages, firstPageParam) => {
      try {
        // Progressing into the FUTURE (Scrolling UP)
        const prevStart = parseISO(firstPageParam.date_to);
        const newStart = addDays(prevStart, 1);
        const newEnd = addDays(newStart, chunkDays - 1);
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
      queryClient.invalidateQueries({ queryKey: journalKeys.all });
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
      queryClient.invalidateQueries({ queryKey: journalKeys.detail(id) });
      queryClient.invalidateQueries({ queryKey: journalKeys.lists() });
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
      queryClient.invalidateQueries({ queryKey: journalKeys.all });
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
    }: {
      journalId: string;
      contactId: string;
      relationshipType: JournalContactRelationshipType;
    }) => addContactRelationship(journalId, contactId, relationshipType),
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
