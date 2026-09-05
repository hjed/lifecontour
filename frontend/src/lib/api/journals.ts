/**
 * Journal API client functions using TanStack Query.
 *
 * Provides typed API functions for journal management operations
 * with proper error handling and caching.
 */

import {
  keepPreviousData,
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
  FitnessMergeMode,
  MergeOverrides,
  ReviewItemsListResponse,
  AttendeeStatus,
  ContactEventRole,
  DailySummaryResponse,
  AutoMergeResponse,
  BlockingTask,
  JournalHasAnchoredTasksMeta,
} from '@/types/journals';
import { JsonApiErrorResponse, JsonApiMeta } from '@/types/api';
import type { HistoryFilters, HistoryListResponse } from '@/types/history';
import {
  API_ENDPOINTS,
  ERROR_MESSAGES,
  SUCCESS_MESSAGES,
} from '@/lib/constants';
import { invalidateAfterMutation } from './invalidate-after-mutation';
import { homeDashboardKeys } from './home-dashboard';
import { taskKeys } from './tasks';
import { journalKeys } from './journal-keys';
import { useUserTimezone } from './settings';
import {
  addDaysToIsoDate,
  futureJournalOptions,
  todayIn,
  FUTURE_WINDOW_DAYS,
} from '@/lib/future-journals';
import type { FutureJournalOption } from '@/lib/future-journals';

/** The largest page the listing endpoint will answer with. */
const FUTURE_PAGE_LIMIT = 100;

/**
 * One day of slack on the window's far bound.
 *
 * `end_date` is sent as a bare date, and the backend reads a bare date as the
 * end of that day in **UTC** (`event_date_range_start <= end_date`). For a user
 * behind UTC the later hours of their own day-90 fall *past* that cutoff, so
 * journals inside a window advertised as ninety days would be dropped from it.
 * The largest offset in use is UTC-12, so one day covers every zone.
 *
 * Overshooting the far edge costs nothing that matters: the window's size is
 * our own choice, the picker shows the nearest journals first, and nothing
 * downstream trims by it — only the strictly-after-today rule filters, and that
 * is at the other end.
 */
const FUTURE_WINDOW_SLACK_DAYS = 1;

// Query Keys
//
// `journalKeys` lives in `./journal-keys` so `tasks.ts` can name a journal
// namespace without importing this module — see that file for the cycle it
// removes. Re-exported here so every existing import keeps working.
export { journalKeys };

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

/** The error code a journal deletion refused by its anchored tasks carries. */
export const JOURNAL_HAS_ANCHORED_TASKS = 'JOURNAL_HAS_ANCHORED_TASKS';

/**
 * A journal deletion the API refused, carrying what the refusal said.
 *
 * Modelled on `TaskApiError` in `./tasks`, and deliberately raised by
 * `deleteJournal` **alone**: it is the one journal call whose refusal a caller
 * has to act on rather than merely report. Every other function in this file
 * keeps throwing a plain `Error`, because widening them all would be churn in
 * service of nothing that reads `code` or `meta`.
 */
export class JournalApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly meta?: JsonApiMeta;

  constructor(
    message: string,
    status: number,
    code?: string,
    meta?: JsonApiMeta
  ) {
    super(message);
    this.name = 'JournalApiError';
    this.status = status;
    this.code = code;
    this.meta = meta;
  }
}

/** One blocker is usable only if every field the explanation renders is there. */
function isBlockingTask(value: unknown): value is BlockingTask {
  const task = value as Partial<BlockingTask> | null;
  return (
    typeof task === 'object' &&
    task !== null &&
    typeof task.task_id === 'number' &&
    typeof task.text === 'string' &&
    typeof task.status === 'string' &&
    Array.isArray(task.blocking_roles) &&
    task.blocking_roles.length > 0 &&
    typeof task.action_journal_id === 'number' &&
    typeof task.action_journal_title === 'string'
  );
}

/**
 * The blocking tasks a refused deletion named, or `null` if it named none.
 *
 * `null` covers every way this can fail to be an explanation — a different
 * error, a different code, a body without `meta`, an empty list, a blocker
 * missing a field a link needs — so a caller has one branch rather than five,
 * and falls back to the refusal's prose in all of them. An **empty** list is
 * `null` on purpose: rendering "these tasks block it" above nothing reads as
 * though nothing does.
 */
export function blockingTasksFrom(error: unknown): BlockingTask[] | null {
  if (!(error instanceof JournalApiError)) return null;
  if (error.code !== JOURNAL_HAS_ANCHORED_TASKS) return null;

  const meta = error.meta as Partial<JournalHasAnchoredTasksMeta> | undefined;
  const blockers = meta?.blocking_tasks;
  if (!Array.isArray(blockers) || blockers.length === 0) return null;
  if (!blockers.every(isBlockingTask)) return null;

  return blockers;
}

async function deleteJournal(id: string): Promise<void> {
  const response = await fetch(API_ENDPOINTS.JOURNALS.BY_ID(id), {
    method: 'DELETE',
    credentials: 'include',
  });

  if (response.ok) return;

  let detail: string | undefined;
  let code: string | undefined;
  let meta: JsonApiMeta | undefined;

  try {
    const errorData: JsonApiErrorResponse = await response.json();
    const error = errorData.errors?.[0];
    detail = error?.detail;
    code = error?.code;
    meta = error?.meta;
  } catch {
    // A gateway page or an empty body. The status is all there is to go on,
    // and it must still produce a usable message rather than a `SyntaxError`.
  }

  throw new JournalApiError(
    detail || ERROR_MESSAGES.DELETE_FAILED,
    response.status,
    code,
    meta
  );
}

async function mergeJournal(
  targetId: string,
  sourceId: string,
  overrides?: MergeOverrides,
  fitnessMergeMode?: FitnessMergeMode
): Promise<JournalResponse> {
  const requestData = {
    type: 'journal-merge' as const,
    attributes: {
      source_journal_id: Number(sourceId),
      ...(overrides ? { overrides } : {}),
      ...(fitnessMergeMode ? { fitness_merge_mode: fitnessMergeMode } : {}),
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

/**
 * The journals nearest the front of a filtered listing, which is the **last**
 * page of it.
 *
 * This exists because the ordering is fixed and cannot be asked for. The
 * listing answers `ORDER BY event_date_range_start DESC`, so within any window
 * the *nearest* journals sort last — and a naive first page of 100 therefore
 * returns the hundred furthest away and silently drops exactly the ones a
 * picker is for. Bounding the window does not fix that: it caps how far the far
 * end reaches, while the end that gets cut is still the near one. An ordinary
 * calendar-synced user fills ninety days with more than a hundred journals.
 *
 * So the page count is read from the response and the **last** page is
 * fetched — one extra round trip, and only for a listing that overflows a page.
 * When that last page is short (a total just past a page boundary leaves it
 * holding one or two) the page before it is taken as well, or a busy user would
 * be offered two journals where a hundred exist.
 *
 * A `sort` parameter on `GET /api/journals` would retire all of this, and is
 * the change worth making if this file grows again.
 */
async function fetchNearestFutureJournals(
  filters: JournalFilters
): Promise<JournalListResponse['data']> {
  const first = await fetchJournals({
    ...filters,
    page: 1,
    limit: FUTURE_PAGE_LIMIT,
  });

  const { pageCount } = getJournalPaginationMeta(first.meta);
  if (pageCount === undefined || pageCount <= 1) {
    return first.data;
  }

  const last = await fetchJournals({
    ...filters,
    page: pageCount,
    limit: FUTURE_PAGE_LIMIT,
  });
  if (last.data.length >= FUTURE_PAGE_LIMIT) {
    return last.data;
  }

  const penultimate =
    pageCount === 2
      ? first
      : await fetchJournals({
          ...filters,
          page: pageCount - 1,
          limit: FUTURE_PAGE_LIMIT,
        });
  return [...penultimate.data, ...last.data];
}

/**
 * The journals a task can be made **due** in: future-dated, nearest first.
 *
 * A thin shell over {@link futureJournalOptions}, which owns the strictly-
 * after-today rule and the ordering, and {@link fetchNearestFutureJournals},
 * which owns getting the *near* end of a listing whose order is fixed the wrong
 * way round. Two choices live here.
 *
 * **The window is bounded, and the search's is not.** Ninety days is what an
 * unsearched picker offers, because "the trip I already planned" is almost
 * always inside it and a year of plans would bury it. A search drops the far
 * bound, because a search that could not reach past ninety days would be a
 * worse answer than no search at all.
 *
 * **`start_date` is sent as today, not tomorrow.** The filter it drives is
 * `event_date_range_end >= start_date`, so it is generous by construction — a
 * journal already under way still matches — and asking for tomorrow would risk
 * dropping a journal starting at local midnight in a zone ahead of UTC. The
 * strictly-after rule is applied afterwards, in the zone where it means
 * something.
 *
 * The zone is the user's **configured** one, because that is the one the
 * server judges by. While that read is in flight the cached value the settings
 * UI writes stands in — and because the two can still disagree, the server's
 * `TASK_DUE_JOURNAL_NOT_FUTURE` remains the authority. This list only keeps a
 * doomed choice off the screen.
 */
export function useFutureJournals(
  options: { search?: string; enabled?: boolean } = {}
) {
  const search = options.search?.trim() ?? '';
  const timezone = useUserTimezone();
  const today = todayIn(timezone);

  return useQuery({
    queryKey: journalKeys.future({ search, today, timezone }),
    queryFn: async (): Promise<FutureJournalOption[]> => {
      const journals = await fetchNearestFutureJournals({
        ...(search ? { search } : {}),
        date_from: today,
        // Search reaches past the window; the unsearched list does not, or the
        // near future would be buried under a year of plans.
        ...(search
          ? {}
          : {
              date_to: addDaysToIsoDate(
                today,
                FUTURE_WINDOW_DAYS + FUTURE_WINDOW_SLACK_DAYS
              ),
            }),
      });
      return futureJournalOptions(journals, { timezone, today });
    },
    enabled: options.enabled ?? true,
    // Each debounced keystroke is a new key, and without this the list is
    // replaced by a loading line every time the user types another letter.
    placeholderData: keepPreviousData,
    staleTime: 5 * 60 * 1000, // 5 minutes
    // `'always'` rather than the app-wide `true`, and the five-minute
    // `staleTime` above is exactly why. The empty picker offers to create a
    // journal **in a new tab**, which is only a recovery if coming back
    // re-reads this list — and the focus handler refetches only queries it
    // considers stale, which this one is not for five minutes. A journal made
    // in another tab cannot invalidate this tab's cache, so the user would
    // return having done what they were asked and find the picker still
    // empty. Opting this one query out of the staleness gate costs one
    // listing request per refocus, and only while a picker is mounted, which
    // is only while one of the two dialogs is open.
    refetchOnWindowFocus: 'always',
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
      // The home dashboard's headline is this same summary entity, so a
      // regeneration stales it whichever surface asked for one. The
      // invalidation lives here rather than in the dashboard card for exactly
      // that reason: regenerating from the journals view leaves the dashboard
      // just as stale as regenerating from the dashboard does.
      void invalidateAfterMutation(queryClient, {
        queryKey: homeDashboardKeys.all,
      });
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
      void refreshAfterJournalTagMutation(queryClient);
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
      void refreshAfterJournalTagMutation(queryClient);
      toast.success(SUCCESS_MESSAGES.TAG_UPDATED);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

/**
 * The home dashboard has to be re-read after **any** journal write.
 *
 * Its headline is today's daily summary row and the four counters beside it are
 * counts of that day's journals, events and contacts; the agenda section reads
 * the same day's event journals with their tags and participants. So rather
 * than deciding per mutation which of those fields it happens to touch — a
 * judgement that would need redoing every time a section lands — every journal
 * write invalidates the dashboard. Without it the app-wide five-minute
 * `staleTime` lets a user edit a journal, return to `/`, and read the pre-edit
 * page as though nothing had happened.
 *
 * **What this does not fix, and cannot.** The backend marks a summary stale
 * *asynchronously*: the write commits an outbox event and `SearchIndexerConsumer`
 * flips the row to `PENDING` afterwards. This invalidation marks the query stale
 * rather than refetching it — the dashboard is not mounted while a journal is
 * being edited, so it is an *inactive* query and React Query re-reads it on its
 * next mount, by which time the consumer has almost always run. It is therefore
 * right for the ordinary path and offers no guarantee on a consumer backlog.
 *
 * **Four backend gaps sit underneath it and no client invalidation can close
 * them**, all recorded as follow-ups in the iteration document. Two are about
 * the date the consumer works out: moving a journal off a day never marks that
 * day stale (it reloads the journal after the write and sees only its new
 * date), and deleting one marks nothing stale at all (`JournalDeleted` carries
 * no date). Two are about which events it listens for — it invalidates on
 * `JournalCreated`/`JournalUpdated`/`JournalDeleted` only, so a contact
 * relationship change (`ContactSummaryRefreshRequested`) leaves `contact_count`
 * stale, and a tag change (`JournalTagAssigned`/`Removed`) leaves the agenda's
 * tags stale. In every case the row stays `GENERATED` with its old values, and
 * re-reading it returns the same stale row — which is why these hooks still
 * invalidate: being right about the cache is worth having even where the
 * server is wrong about the row.
 */
const REFRESH_HOME_DASHBOARD = { queryKey: homeDashboardKeys.all };

/**
 * Refreshes everything a journal tag mutation can change.
 *
 * The tag namespace feeds the sidebar tree and the detail page's tag editor;
 * the journal queries feed the chips on the list and on any open journal.
 *
 * This neither splices the cache by hand nor delays the invalidation behind a
 * timer: the write commits in the service layer before the response is sent, so
 * there is no read-after-write race to wait out. `useDeleteTag` / `useMergeTag`
 * in `lib/api/contacts.ts` are the contact-side twins (#1204).
 */
function refreshAfterJournalTagMutation(
  queryClient: ReturnType<typeof useQueryClient>
): Promise<void> {
  return invalidateAfterMutation(
    queryClient,
    { queryKey: journalTagKeys.lists() },
    { queryKey: journalKeys.all },
    REFRESH_HOME_DASHBOARD
  );
}

/**
 * Deletes a journal tag, which also un-assigns it from every journal.
 */
export function useDeleteJournalTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => deleteJournalTag(id),
    onSuccess: () => {
      void refreshAfterJournalTagMutation(queryClient);
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
    onSuccess: () => {
      void refreshAfterJournalTagMutation(queryClient);
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
      void invalidateAfterMutation(queryClient, {
        queryKey: calendarKeys.lists(),
      });
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
      void invalidateAfterMutation(queryClient, {
        queryKey: calendarKeys.lists(),
      });
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
      void invalidateAfterMutation(queryClient, {
        queryKey: calendarKeys.lists(),
      });
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
        void invalidateAfterMutation(
          queryClient,
          { queryKey: journalKeys.all },
          REFRESH_HOME_DASHBOARD
        );
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
        void invalidateAfterMutation(
          queryClient,
          { queryKey: journalKeys.detail(id) },
          { queryKey: journalKeys.lists() },
          // A task's read shapes embed their journals — title, date, cancelled,
          // and the lapse derived from them — so a journal write changes what a
          // task query would answer. Moving a date into the past or cancelling
          // the journal is what *lapses* its due tasks, and the journal detail
          // view is showing those very tasks.
          { queryKey: taskKeys.all },
          REFRESH_HOME_DASHBOARD
        );
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
        void invalidateAfterMutation(
          queryClient,
          { queryKey: journalKeys.lists() },
          // Deleting a journal that is only an *intermediate* link is
          // permitted, and it removes that link from every task that held it.
          { queryKey: taskKeys.all },
          REFRESH_HOME_DASHBOARD
        );
      }, 150);
      toast.success(SUCCESS_MESSAGES.JOURNAL_DELETED);
    },
    onError: (error: Error) => {
      // The anchored-tasks refusal is an explanation with links in it, and
      // the delete dialog renders it in place. Toasting here as well would
      // both duplicate the prose and put the one actionable part — the
      // journals to open — somewhere it cannot be clicked before it fades.
      if (blockingTasksFrom(error)) return;
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
      fitnessMergeMode,
    }: {
      targetId: string;
      sourceId: string;
      overrides?: MergeOverrides;
      fitnessMergeMode?: FitnessMergeMode;
    }) => mergeJournal(targetId, sourceId, overrides, fitnessMergeMode),
    onSuccess: (_, { targetId, sourceId }) => {
      void invalidateAfterMutation(
        queryClient,
        { queryKey: journalKeys.detail(targetId) },
        { queryKey: journalKeys.detail(sourceId) },
        { queryKey: journalKeys.lists() },
        { queryKey: reviewItemKeys.all },
        // A merge re-points the absorbed journal's task links at the survivor,
        // so a listing cached before it would omit the tasks that moved.
        { queryKey: taskKeys.all },
        REFRESH_HOME_DASHBOARD
      );
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
      void invalidateAfterMutation(
        queryClient,
        { queryKey: journalKeys.detail(journalId) },
        { queryKey: journalKeys.lists() },
        // See useUpdateJournal: a task embeds its journals, so an inline field
        // save — the date range above all — can change a task's lapse state.
        { queryKey: taskKeys.all },
        REFRESH_HOME_DASHBOARD
      );
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
      void invalidateAfterMutation(
        queryClient,
        { queryKey: journalKeys.detail(journalId) },
        { queryKey: journalKeys.lists() },
        REFRESH_HOME_DASHBOARD
      );
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
      void invalidateAfterMutation(
        queryClient,
        { queryKey: journalKeys.detail(journalId) },
        { queryKey: journalKeys.lists() },
        REFRESH_HOME_DASHBOARD
      );
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
      void invalidateAfterMutation(
        queryClient,
        { queryKey: journalKeys.detail(journalId) },
        { queryKey: journalKeys.lists() },
        REFRESH_HOME_DASHBOARD
      );
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
      void invalidateAfterMutation(
        queryClient,
        { queryKey: journalKeys.detail(journalId) },
        { queryKey: journalKeys.lists() },
        REFRESH_HOME_DASHBOARD
      );
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
      void invalidateAfterMutation(
        queryClient,
        { queryKey: journalKeys.detail(journalId) },
        { queryKey: journalKeys.lists() },
        REFRESH_HOME_DASHBOARD
      );
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
      void invalidateAfterMutation(
        queryClient,
        { queryKey: journalKeys.detail(journalId) },
        { queryKey: journalKeys.lists() },
        REFRESH_HOME_DASHBOARD
      );
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
      void invalidateAfterMutation(
        queryClient,
        { queryKey: journalKeys.detail(journalId) },
        { queryKey: journalKeys.lists() },
        REFRESH_HOME_DASHBOARD
      );
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
      void invalidateAfterMutation(
        queryClient,
        { queryKey: journalKeys.detail(journalId) },
        { queryKey: journalKeys.lists() },
        REFRESH_HOME_DASHBOARD
      );
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
      void invalidateAfterMutation(queryClient, {
        queryKey: journalSeriesKeys.lists(),
      });
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
      void invalidateAfterMutation(
        queryClient,
        { queryKey: journalSeriesKeys.all },
        { queryKey: journalKeys.details() }
      );
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
      void invalidateAfterMutation(
        queryClient,
        { queryKey: journalKeys.detail(journalId) },
        { queryKey: journalSeriesKeys.detail(seriesId) }
      );
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
      void invalidateAfterMutation(
        queryClient,
        { queryKey: journalKeys.detail(journalId) },
        { queryKey: journalSeriesKeys.detail(seriesId) }
      );
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
        { queryKey: reviewItemKeys.lists() }
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
      void invalidateAfterMutation(
        queryClient,
        { queryKey: reviewItemKeys.all },
        { queryKey: journalKeys.lists() },
        { queryKey: journalKeys.details() }
      );
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
      void invalidateAfterMutation(
        queryClient,
        { queryKey: reviewItemKeys.all },
        { queryKey: journalKeys.lists() },
        { queryKey: journalKeys.details() },
        REFRESH_HOME_DASHBOARD
      );
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
