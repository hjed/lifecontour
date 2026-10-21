/**
 * Contact API client functions using TanStack Query.
 *
 * Provides typed API functions for contact management operations
 * with proper error handling and caching.
 */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InvalidateQueryFilters,
  type QueryClient,
} from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  ContactAddressAttributes,
  ContactHistoryListResponse,
  ContactListResponse,
  ContactMethodAttributes,
  ContactResponse,
  ContactCreateData,
  ContactUpdateData,
  ContactFormData,
  ContactFilters,
  TagListResponse,
  TagCreateAttributes,
  TagResponse,
  ContactFieldResponse,
  ContactSummaryUpdateData,
  ImportantDateAttributes,
  CustomDateTypeResponse,
  CustomDateTypeListResponse,
  MergeContactOverrides,
} from '@/types/contacts';
import { JsonApiErrorResponse, JsonApiMeta } from '@/types/api';
import type { HistoryFilters } from '@/types/history';
import {
  API_ENDPOINTS,
  ERROR_MESSAGES,
  SUCCESS_MESSAGES,
} from '@/lib/constants';
import {
  AGGREGATE_LABELS,
  isWriteConflict,
  toastUnlessConflict,
} from '@/lib/write-conflicts';
import {
  aggregateWrite,
  guardedWrite,
  sendGuarded,
  type AggregateRef,
} from './aggregate-write';
import { sendConditional, type ConditionalResult } from './conditional-request';
import { invalidateAfterMutation } from './invalidate-after-mutation';
import { taskKeys } from './tasks';
import {
  storeVersioned,
  unwrapResource,
  updateResource,
  type Versioned,
} from './versioned-cache';

// Query Keys
export const contactKeys = {
  all: ['contacts'] as const,
  lists: () => [...contactKeys.all, 'list'] as const,
  list: (filters: ContactFilters) => [...contactKeys.lists(), filters] as const,
  infiniteLists: () => [...contactKeys.lists(), 'infinite'] as const,
  infiniteList: (filters: ContactFilters) =>
    [...contactKeys.infiniteLists(), filters] as const,
  details: () => [...contactKeys.all, 'detail'] as const,
  detail: (id: string) => [...contactKeys.details(), id] as const,
  tags: (id: string) => [...contactKeys.detail(id), 'tags'] as const,
  searches: () => [...contactKeys.all, 'search'] as const,
  search: (query: string) => [...contactKeys.searches(), query] as const,
  infiniteSearches: () => [...contactKeys.searches(), 'infinite'] as const,
  infiniteSearch: (query: string) =>
    [...contactKeys.infiniteSearches(), query] as const,
};

/**
 * The contact aggregate a write belongs to: every write to the contact or to
 * one of its rows is guarded by, and serialised on, the contact's `ETag`.
 */
function contactAggregate(contactId: string): AggregateRef {
  return {
    kind: 'contact',
    id: contactId,
    detailKey: contactKeys.detail(contactId),
  };
}

/** A field edit in words, for the conflict dialog: "Nickname → Bob". */
function describeFieldEdit(fieldName: string, value: string): string {
  return `${AGGREGATE_LABELS.contact[fieldName] ?? fieldName} → ${value}`;
}

export const tagKeys = {
  all: ['tags'] as const,
  lists: () => [...tagKeys.all, 'list'] as const,
};

interface ContactPaginationMeta {
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

function omitPage<T extends { page?: number }>(value: T): Omit<T, 'page'> {
  const nextValue = { ...value };
  delete nextValue.page;
  return nextValue as Omit<T, 'page'>;
}

function getListQueryFilters(filters: ContactFilters): ContactFilters {
  return omitPage(filters);
}

function getNextContactPageParam(
  lastPage: ContactListResponse
): number | undefined {
  const { currentPage, pageCount } = getContactPaginationMeta(lastPage.meta);

  if (
    currentPage === undefined ||
    pageCount === undefined ||
    currentPage >= pageCount
  ) {
    return undefined;
  }

  return currentPage + 1;
}

export function getContactPaginationMeta(
  meta?: JsonApiMeta
): ContactPaginationMeta {
  return {
    totalCount: getMetaNumber(meta, 'total_count', 'total'),
    currentPage: getMetaNumber(meta, 'current_page', 'page'),
    pageCount: getMetaNumber(meta, 'page_count', 'total_pages', 'totalPages'),
    perPage: getMetaNumber(meta, 'per_page', 'limit'),
  };
}

// API Functions
export async function fetchContacts(
  filters: ContactFilters = {}
): Promise<ContactListResponse> {
  const params = new URLSearchParams();

  if (filters.search) params.append('search', filters.search);
  if (filters.tags?.length) {
    filters.tags.forEach(tag => {
      // Convert tag to integer ID if it's a string representation
      const tagId = typeof tag === 'string' ? Number.parseInt(tag, 10) : tag;
      if (!Number.isNaN(tagId)) {
        params.append('tag_ids', tagId.toString());
      }
    });
  }
  if (filters.favourite !== undefined) {
    params.append('favourite', filters.favourite.toString());
  }
  if (filters.created_after)
    params.append('created_after', filters.created_after);
  if (filters.created_before)
    params.append('created_before', filters.created_before);
  if (filters.page !== undefined)
    params.append('page', filters.page.toString());
  if (filters.limit !== undefined)
    params.append('limit', filters.limit.toString());

  const url = `${API_ENDPOINTS.CONTACTS.BASE}?${params.toString()}`;

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

/** Reads a contact together with its `ETag`, the version later writes send. */
async function fetchContact(id: string): Promise<Versioned<ContactResponse>> {
  const response = await fetch(API_ENDPOINTS.CONTACTS.BY_ID(id), {
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

  return {
    resource: await response.json(),
    etag: response.headers.get('ETag'),
  };
}

async function createContact(data: ContactFormData): Promise<ContactResponse> {
  const requestData: ContactCreateData = {
    type: 'contacts',
    attributes: data,
  };

  const response = await fetch(API_ENDPOINTS.CONTACTS.BASE, {
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

async function updateContact(
  id: string,
  data: ContactFormData,
  ifMatch: string | null
): Promise<ConditionalResult<ContactResponse>> {
  const requestData: ContactUpdateData = {
    type: 'contacts',
    id,
    attributes: data,
  };

  return sendConditional<ContactResponse>(API_ENDPOINTS.CONTACTS.BY_ID(id), {
    method: 'PUT',
    body: { data: requestData },
    ifMatch,
    fallbackMessage: ERROR_MESSAGES.UPDATE_FAILED,
  });
}

async function deleteContact(id: string): Promise<void> {
  const response = await fetch(API_ENDPOINTS.CONTACTS.BY_ID(id), {
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

async function fetchContactTags(contactId: string): Promise<TagListResponse> {
  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/tags`,
    {
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
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

async function searchContacts(
  query: string,
  options: {
    page?: number;
    limit?: number;
    tags?: string[];
  } = {}
): Promise<ContactListResponse> {
  const params = new URLSearchParams();
  params.append('q', query);

  if (options.page) params.append('page', options.page.toString());
  if (options.limit) params.append('limit', options.limit.toString());
  if (options.tags?.length) {
    // For search API, keep using 'tags' as the backend search endpoint expects tag names
    options.tags.forEach(tag => params.append('tags', tag));
  }

  const url = `${API_ENDPOINTS.SEARCH.CONTACTS}?${params.toString()}`;

  const response = await fetch(url, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.SEARCH_FAILED
    );
  }

  return response.json();
}

async function fetchTags(): Promise<TagListResponse> {
  const response = await fetch('/api/tags?limit=1000', {
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

export async function toggleContactFavourite(
  contactId: string
): Promise<ContactResponse> {
  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/favourite`,
    {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
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

// React Query Hooks
export function useContacts(
  filters: ContactFilters = {},
  options: { enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: contactKeys.list(filters),
    queryFn: () => fetchContacts(filters),
    staleTime: 5 * 60 * 1000, // 5 minutes
    enabled: options.enabled,
  });
}

export function useInfiniteContacts(
  filters: ContactFilters = {},
  options: { enabled?: boolean } = {}
) {
  const initialPage = filters.page ?? 1;

  return useInfiniteQuery({
    queryKey: contactKeys.infiniteList(getListQueryFilters(filters)),
    queryFn: ({ pageParam }) =>
      fetchContacts({
        ...filters,
        page: pageParam,
      }),
    initialPageParam: initialPage,
    getNextPageParam: getNextContactPageParam,
    staleTime: 5 * 60 * 1000, // 5 minutes
    enabled: options.enabled,
  });
}

export function useContact(id: string) {
  return useQuery({
    queryKey: contactKeys.detail(id),
    queryFn: () => fetchContact(id),
    select: unwrapResource,
    enabled: !!id,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

export function useContactTags(
  id: string,
  options: { enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: contactKeys.tags(id),
    queryFn: () => fetchContactTags(id),
    enabled: options.enabled !== false && !!id,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

export function useSearchContacts(
  query: string,
  options: {
    page?: number;
    limit?: number;
    tags?: string[];
  } = {},
  queryOptions: { enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: contactKeys.search(`${query}-${JSON.stringify(options)}`),
    queryFn: () => searchContacts(query, options),
    enabled: queryOptions.enabled ?? query.length > 0,
    staleTime: 2 * 60 * 1000, // 2 minutes for search results
  });
}

export function useInfiniteSearchContacts(
  query: string,
  options: {
    page?: number;
    limit?: number;
    tags?: string[];
  } = {},
  queryOptions: { enabled?: boolean } = {}
) {
  const initialPage = options.page ?? 1;
  const searchOptions = omitPage(options);

  return useInfiniteQuery({
    queryKey: contactKeys.infiniteSearch(
      `${query}-${JSON.stringify(searchOptions)}`
    ),
    queryFn: ({ pageParam }) =>
      searchContacts(query, {
        ...searchOptions,
        page: pageParam,
      }),
    initialPageParam: initialPage,
    getNextPageParam: getNextContactPageParam,
    enabled: queryOptions.enabled ?? query.length > 0,
    staleTime: 2 * 60 * 1000, // 2 minutes for search results
  });
}

export function useTags() {
  return useQuery({
    queryKey: tagKeys.lists(),
    queryFn: fetchTags,
    staleTime: 10 * 60 * 1000, // 10 minutes
  });
}

export function useCreateContact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createContact,
    onSuccess: () => {
      void invalidateAfterMutation(queryClient, { queryKey: contactKeys.all });
      toast.success(SUCCESS_MESSAGES.CONTACT_CREATED);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useUpdateContact(id: string) {
  const queryClient = useQueryClient();
  const aggregate = contactAggregate(id);

  return useMutation({
    ...aggregateWrite<ContactFormData>(aggregate, () => 'Contact details'),
    mutationFn: (data: ContactFormData) =>
      sendGuarded(queryClient, aggregate.detailKey, ifMatch =>
        updateContact(id, data, ifMatch)
      ),
    onSuccess: data => {
      // The tag the write returned is already stored; the body is the same
      // version re-read.
      updateResource<ContactResponse>(
        queryClient,
        aggregate.detailKey,
        () => data
      );
      void invalidateAfterMutation(
        queryClient,
        { queryKey: contactKeys.lists() },
        // A task embeds its linked contacts by display name and photo rather
        // than by reference, so a rename leaves the old name on every task row
        // showing that contact until the task caches are refreshed.
        { queryKey: taskKeys.all }
      );
      toast.success(SUCCESS_MESSAGES.CONTACT_UPDATED);
    },
    onError: (error: Error) => {
      // A conflict is reported by the conflict dialog instead.
      if (!isWriteConflict(error)) toast.error(error.message);
    },
  });
}

export function useDeleteContact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteContact,
    onSuccess: () => {
      void invalidateAfterMutation(
        queryClient,
        { queryKey: contactKeys.all },
        // See useUpdateContact: a deleted contact stays on its task rows until
        // the task caches drop the embedded copy.
        { queryKey: taskKeys.all }
      );
      toast.success(SUCCESS_MESSAGES.CONTACT_DELETED);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useToggleContactFavourite() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: toggleContactFavourite,
    onSuccess: data => {
      const contactId = data.data.id;
      void invalidateAfterMutation(
        queryClient,
        { queryKey: contactKeys.detail(contactId) },
        { queryKey: contactKeys.lists() }
      );
      const isFavourite = data.data.attributes.is_favourite;
      toast.success(
        isFavourite
          ? 'Contact added to favourites'
          : 'Contact removed from favourites'
      );
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

// Contact Merge API Functions

/**
 * Merge a source contact into a surviving contact.
 *
 * `survivorId` keeps its ID; the source is absorbed and deleted. Per-field
 * `overrides` carry the already-resolved survivor / source / custom values for
 * conflicting scalar fields; omitted fields fall back to the backend default
 * policy (survivor wins, prefer non-empty). Mirrors {@link mergeTag} /
 * `mergeJournal`.
 */
async function mergeContact(
  survivorId: string,
  sourceId: string,
  overrides?: MergeContactOverrides
): Promise<ContactResponse> {
  const requestData = {
    type: 'contact-merge' as const,
    attributes: {
      source_contact_id: Number(sourceId),
      ...(overrides ? { overrides } : {}),
    },
  };

  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BY_ID(survivorId)}/merge`,
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
      errorData.errors?.[0]?.detail || 'Failed to merge contacts'
    );
  }

  return response.json();
}

export function useMergeContact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      survivorId,
      sourceId,
      overrides,
    }: {
      survivorId: string;
      sourceId: string;
      overrides?: MergeContactOverrides;
    }) => mergeContact(survivorId, sourceId, overrides),
    onSuccess: (_data, { survivorId, sourceId }) => {
      // The merge deletes the source and consolidates the aggregate onto the
      // survivor, so refresh the full contacts cache plus both detail entries.
      void invalidateAfterMutation(
        queryClient,
        { queryKey: contactKeys.all },
        { queryKey: contactKeys.detail(survivorId) },
        { queryKey: contactKeys.detail(sourceId) },
        // The merge writes an audit row to field_history; refresh the activity
        // feed (backed by historyKeys) so it surfaces without waiting for a
        // natural refetch.
        { queryKey: historyKeys.all },
        // The source contact is deleted, so any task row still holding its
        // embedded copy would go on showing a contact that no longer exists.
        { queryKey: taskKeys.all }
      );
      toast.success('Contacts merged successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

// Field-level update functions
async function updateContactField(
  contactId: string,
  fieldName: string,
  value: string,
  ifMatch: string | null
): Promise<ConditionalResult<ContactFieldResponse>> {
  return sendConditional<ContactFieldResponse>(
    `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/fields/${fieldName}`,
    {
      method: 'PATCH',
      body: { data: { type: 'contact_fields', attributes: { value } } },
      ifMatch,
      fallbackMessage: ERROR_MESSAGES.UPDATE_FAILED,
    }
  );
}

interface ContactFieldEdit {
  fieldName: string;
  value: string;
}

export function useUpdateContactField(contactId: string) {
  const queryClient = useQueryClient();
  const aggregate = contactAggregate(contactId);

  return useMutation({
    ...aggregateWrite<ContactFieldEdit>(aggregate, ({ fieldName, value }) =>
      describeFieldEdit(fieldName, value)
    ),
    mutationFn: ({ fieldName, value }: ContactFieldEdit) =>
      sendGuarded(queryClient, aggregate.detailKey, ifMatch =>
        updateContactField(contactId, fieldName, value, ifMatch)
      ),
    onSuccess: (data: ContactFieldResponse) => {
      // Merge the updated field into the cached contact; the write's tag is
      // already stored.
      updateResource<ContactResponse>(
        queryClient,
        aggregate.detailKey,
        contact => ({
          ...contact,
          data: {
            ...contact.data,
            attributes: {
              ...contact.data.attributes,
              [data.data.attributes.field_name]: data.data.attributes.new_value,
            },
          },
        })
      );

      // We still need to invalidate lists so search tables and sidebars reflect the updated field
      void invalidateAfterMutation(
        queryClient,
        { queryKey: contactKeys.lists() },
        // See useUpdateContact: a task carries an embedded copy of its
        // contacts' names, so an inline rename must reach the task caches too.
        { queryKey: taskKeys.all }
      );
    },
    onError: (error: Error) => {
      // Don't show toast here - let the component handle it. A conflict is
      // reported by the conflict dialog.
      if (!isWriteConflict(error)) console.error('Field update failed:', error);
    },
  });
}

// Contact History API Functions
export const historyKeys = {
  all: ['contact-history'] as const,
  list: (contactId: string, page?: number, limit?: number) =>
    [...historyKeys.all, contactId, { page, limit }] as const,
};

export async function fetchContactHistory(
  contactId: string,
  filters: HistoryFilters = {}
): Promise<ContactHistoryListResponse> {
  const params = new URLSearchParams();

  if (filters.page) params.append('page', filters.page.toString());
  if (filters.limit) params.append('limit', filters.limit.toString());

  const url = `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/history?${params.toString()}`;

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

export function useContactHistory(
  contactId: string,
  filters: HistoryFilters = {},
  options: { enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: historyKeys.list(contactId, filters.page, filters.limit),
    queryFn: () =>
      fetchContactHistory(contactId, {
        page: filters.page,
        limit: filters.limit,
      }),
    enabled: options.enabled !== false && !!contactId,
    staleTime: 2 * 60 * 1000, // 2 minutes for history
  });
}

// Contact Methods and Addresses API Functions
//
// Every write here is to one of the contact's rows, and is guarded by the
// contact's tag: see `contactAggregate`.

const contactRowUrl = (contactId: string, rows: 'methods' | 'addresses') =>
  `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/${rows}`;

function updateContactRowField(
  contactId: string,
  rows: 'methods' | 'addresses',
  rowId: string,
  fieldName: string,
  value: string | boolean,
  ifMatch: string | null
): Promise<ConditionalResult<unknown>> {
  const type =
    rows === 'methods' ? 'contact_method_fields' : 'contact_address_fields';
  return sendConditional<unknown>(
    `${contactRowUrl(contactId, rows)}/${rowId}/fields/${fieldName}`,
    {
      method: 'PATCH',
      body: { data: { type, attributes: { value } } },
      ifMatch,
      fallbackMessage: ERROR_MESSAGES.UPDATE_FAILED,
    }
  );
}

function addContactRow(
  contactId: string,
  rows: 'methods' | 'addresses',
  attributes: ContactMethodAttributes | ContactAddressAttributes,
  ifMatch: string | null
): Promise<ConditionalResult<ContactResponse>> {
  const type = rows === 'methods' ? 'contact_methods' : 'contact_addresses';
  return sendConditional<ContactResponse>(contactRowUrl(contactId, rows), {
    method: 'POST',
    body: { data: { type, attributes } },
    ifMatch,
    fallbackMessage: ERROR_MESSAGES.CREATE_FAILED,
  });
}

function deleteContactRow(
  contactId: string,
  rows: 'methods' | 'addresses',
  rowId: string,
  ifMatch: string | null
): Promise<ConditionalResult<undefined>> {
  return sendConditional(`${contactRowUrl(contactId, rows)}/${rowId}`, {
    method: 'DELETE',
    ifMatch,
    fallbackMessage: ERROR_MESSAGES.DELETE_FAILED,
  });
}

/** Refreshes what a write to one of the contact's rows changed. */
function invalidateContactRows(
  queryClient: QueryClient,
  contactId: string,
  ...extra: InvalidateQueryFilters[]
): void {
  void invalidateAfterMutation(
    queryClient,
    { queryKey: contactKeys.detail(contactId) },
    { queryKey: contactKeys.lists() },
    ...extra
  );
}

// React Query Hooks for Contact Methods

export function useAddContactMethod(contactId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    ...guardedWrite(
      queryClient,
      contactAggregate(contactId),
      ({ method }: { method: ContactMethodAttributes }, ifMatch) =>
        addContactRow(contactId, 'methods', method, ifMatch),
      ({ method }) => `Add contact method ${method.value}`,
      { bodyIsResource: true }
    ),
    onSuccess: () => {
      invalidateContactRows(queryClient, contactId);
      toast.success('Contact method added successfully');
    },
    onError: toastUnlessConflict,
  });
}

export function useUpdateContactMethodField(contactId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    ...guardedWrite(
      queryClient,
      contactAggregate(contactId),
      (
        {
          methodId,
          fieldName,
          value,
        }: { methodId: string; fieldName: string; value: string },
        ifMatch
      ) =>
        updateContactRowField(
          contactId,
          'methods',
          methodId,
          fieldName,
          value,
          ifMatch
        ),
      ({ value }) => `Contact method → ${value}`
    ),
    onSuccess: () => invalidateContactRows(queryClient, contactId),
    // No toast: the inline editor shows the error, and the dialog a conflict.
  });
}

export function useDeleteContactMethod(contactId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    ...guardedWrite(
      queryClient,
      contactAggregate(contactId),
      ({ methodId }: { methodId: string }, ifMatch) =>
        deleteContactRow(contactId, 'methods', methodId, ifMatch),
      () => 'Delete a contact method'
    ),
    onSuccess: () => {
      invalidateContactRows(queryClient, contactId);
      toast.success('Contact method deleted successfully');
    },
    onError: toastUnlessConflict,
  });
}

// React Query Hooks for Contact Addresses

export function useAddContactAddress(contactId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    ...guardedWrite(
      queryClient,
      contactAggregate(contactId),
      ({ address }: { address: ContactAddressAttributes }, ifMatch) =>
        addContactRow(contactId, 'addresses', address, ifMatch),
      () => 'Add an address',
      { bodyIsResource: true }
    ),
    onSuccess: () => {
      invalidateContactRows(queryClient, contactId);
      toast.success('Contact address added successfully');
    },
    onError: toastUnlessConflict,
  });
}

/** One edit to an address, possibly of several of its fields. */
interface ContactAddressEdit {
  addressId: string;
  fields: Record<string, string>;
}

/**
 * Saves an edit to one address as a single mutation, however many of its
 * fields it changes.
 *
 * The API takes one field per request, but the edit is one change to the
 * user: a conflict part-way through must replay all of it on "Keep mine", not
 * only the field that was refused. Each request is guarded by the tag the
 * previous one returned.
 */
export function useUpdateContactAddressFields(contactId: string) {
  const queryClient = useQueryClient();
  const aggregate = contactAggregate(contactId);

  return useMutation({
    ...aggregateWrite<ContactAddressEdit>(
      aggregate,
      ({ fields }) =>
        `Address → ${Object.values(fields).filter(Boolean).join(', ')}`
    ),
    mutationFn: async ({ addressId, fields }: ContactAddressEdit) => {
      for (const [fieldName, value] of Object.entries(fields)) {
        await sendGuarded(queryClient, aggregate.detailKey, ifMatch =>
          updateContactRowField(
            contactId,
            'addresses',
            addressId,
            fieldName,
            value,
            ifMatch
          )
        );
      }
    },
    onSuccess: () => invalidateContactRows(queryClient, contactId),
    // No toast: the inline editor shows the error, and the dialog a conflict.
  });
}

export function useDeleteContactAddress(contactId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    ...guardedWrite(
      queryClient,
      contactAggregate(contactId),
      ({ addressId }: { addressId: string }, ifMatch) =>
        deleteContactRow(contactId, 'addresses', addressId, ifMatch),
      () => 'Delete an address'
    ),
    onSuccess: () => {
      invalidateContactRows(queryClient, contactId);
      toast.success('Contact address deleted successfully');
    },
    onError: toastUnlessConflict,
  });
}

/** Which of a contact's value lists an archive or restore applies to. */
export type ContactValueKind = 'method' | 'address';

interface ContactValueArchive {
  kind: ContactValueKind;
  id: string;
  archived: boolean;
}

/**
 * Archive or restore one of a contact's emails, phones or addresses.
 *
 * Archiving the primary value also makes it no longer primary; the server
 * does that, so the contact is refetched rather than patched in the cache.
 */
export function useSetContactValueArchived(contactId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    ...guardedWrite(
      queryClient,
      contactAggregate(contactId),
      ({ kind, id, archived }: ContactValueArchive, ifMatch) =>
        updateContactRowField(
          contactId,
          kind === 'method' ? 'methods' : 'addresses',
          id,
          'is_archived',
          archived,
          ifMatch
        ),
      ({ archived }) => (archived ? 'Archive a value' : 'Restore a value')
    ),
    onSuccess: (_, { archived }) => {
      invalidateContactRows(queryClient, contactId, {
        queryKey: historyKeys.all,
      });
      toast.success(archived ? 'Archived' : 'Restored');
    },
    onError: toastUnlessConflict,
  });
}

// Contact Important Dates Management API Functions
//
// These write against date-scoped endpoints rather than the whole-contact PUT.
// That PUT replaces the entire date list, so it churns every date's id on each
// save and records no per-field history for an edit. See LOCAL-176.

const importantDatesUrl = (contactId: string) =>
  `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/important-dates`;

async function readErrorMessage(
  response: Response,
  fallback: string
): Promise<string> {
  const errorData: JsonApiErrorResponse = await response.json();
  return errorData.errors?.[0]?.detail || fallback;
}

// These answer with the whole contact and the tag of that same read, which is
// kept with it: dropping it would leave later guarded edits unguarded.
function addContactImportantDate(
  contactId: string,
  date: ImportantDateAttributes
): Promise<ConditionalResult<ContactResponse>> {
  return sendConditional<ContactResponse>(importantDatesUrl(contactId), {
    method: 'POST',
    body: { data: { type: 'contact_important_dates', attributes: date } },
    ifMatch: null,
    fallbackMessage: ERROR_MESSAGES.CREATE_FAILED,
  });
}

function updateContactImportantDate(
  contactId: string,
  dateId: string,
  date: ImportantDateAttributes
): Promise<ConditionalResult<ContactResponse>> {
  return sendConditional<ContactResponse>(
    `${importantDatesUrl(contactId)}/${dateId}`,
    {
      method: 'PUT',
      body: {
        data: { type: 'contact_important_dates', id: dateId, attributes: date },
      },
      ifMatch: null,
      fallbackMessage: ERROR_MESSAGES.UPDATE_FAILED,
    }
  );
}

async function deleteContactImportantDate(
  contactId: string,
  dateId: string
): Promise<void> {
  const response = await fetch(`${importantDatesUrl(contactId)}/${dateId}`, {
    method: 'DELETE',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error(
      await readErrorMessage(response, ERROR_MESSAGES.DELETE_FAILED)
    );
  }
}

export function useAddContactImportantDate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      contactId,
      date,
    }: {
      contactId: string;
      date: ImportantDateAttributes;
    }) => addContactImportantDate(contactId, date),
    onSuccess: ({ body, etag }, { contactId }) => {
      // Seed rather than invalidate: these endpoints answer with the whole
      // contact, so the cache can be made current synchronously. An
      // invalidation alone resolves the mutation before the refetch lands, and
      // the inline editor seeds its inputs from the cache when it reopens - so
      // a second edit would submit the values the first one just replaced.
      storeVersioned(queryClient, contactKeys.detail(contactId), body, etag);
      void invalidateAfterMutation(
        queryClient,
        { queryKey: contactKeys.lists() },
        // The add writes a "created" marker to field_history; refresh the
        // activity feed (historyKeys) so it surfaces without a manual reload,
        // exactly as the merge does.
        { queryKey: historyKeys.all }
      );
      toast.success('Important date added successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useUpdateContactImportantDate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      contactId,
      dateId,
      date,
    }: {
      contactId: string;
      dateId: string;
      date: ImportantDateAttributes;
    }) => updateContactImportantDate(contactId, dateId, date),
    onSuccess: ({ body, etag }, { contactId }) => {
      // See useAddContactImportantDate: the editor reopens from this cache, so
      // it has to be current by the time the mutation settles.
      storeVersioned(queryClient, contactKeys.detail(contactId), body, etag);
      void invalidateAfterMutation(
        queryClient,
        { queryKey: contactKeys.lists() },
        // An edit writes a row per changed field to field_history.
        { queryKey: historyKeys.all }
      );
      toast.success('Important date updated successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useDeleteContactImportantDate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      contactId,
      dateId,
    }: {
      contactId: string;
      dateId: string;
    }) => deleteContactImportantDate(contactId, dateId),
    onSuccess: (_, { contactId }) => {
      // A delete answers 204, so there is no payload to seed the cache with and
      // the detail query is invalidated instead. No editor reopens from it.
      void invalidateAfterMutation(
        queryClient,
        { queryKey: contactKeys.detail(contactId) },
        { queryKey: contactKeys.lists() },
        // The delete writes a "deleted" marker to field_history.
        { queryKey: historyKeys.all }
      );
      toast.success('Important date deleted successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

// Contact Tag Management API Functions

async function assignTagToContact(
  contactId: string,
  tagId: string
): Promise<void> {
  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/tags`,
    {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        data: {
          type: 'tags',
          id: tagId,
        },
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

async function removeTagFromContact(
  contactId: string,
  tagId: string
): Promise<void> {
  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/tags/${tagId}`,
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
}

async function createTag(
  attributes: TagCreateAttributes
): Promise<TagResponse> {
  const response = await fetch('/api/tags', {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      data: {
        type: 'tags',
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

// React Query Hooks for Contact Tag Management

export function useAssignContactTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ contactId, tagId }: { contactId: string; tagId: string }) =>
      assignTagToContact(contactId, tagId),
    onSuccess: (_, { contactId }) => {
      void invalidateAfterMutation(
        queryClient,
        { queryKey: contactKeys.detail(contactId) },
        { queryKey: contactKeys.tags(contactId) },
        { queryKey: contactKeys.lists() }
      );
      toast.success(SUCCESS_MESSAGES.TAG_ASSIGNED);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useRemoveContactTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ contactId, tagId }: { contactId: string; tagId: string }) =>
      removeTagFromContact(contactId, tagId),
    // Optimistically remove the badge so the UI doesn't depend on the refetch
    // landing (the backend commits the delete at request teardown, so an
    // immediate refetch can still observe the tag — see the read-after-write
    // note in the transaction-ordering issue).
    onMutate: async ({ contactId, tagId }) => {
      await queryClient.cancelQueries({
        queryKey: contactKeys.tags(contactId),
      });
      const previousTags = queryClient.getQueryData<TagListResponse>(
        contactKeys.tags(contactId)
      );
      if (previousTags) {
        queryClient.setQueryData<TagListResponse>(contactKeys.tags(contactId), {
          ...previousTags,
          data: previousTags.data.filter(tag => tag.id !== tagId),
        });
      }
      return { previousTags };
    },
    onError: (error: Error, { contactId }, context) => {
      if (context?.previousTags) {
        queryClient.setQueryData(
          contactKeys.tags(contactId),
          context.previousTags
        );
      }
      toast.error(error.message);
    },
    onSuccess: () => {
      toast.success(SUCCESS_MESSAGES.TAG_REMOVED);
    },
    onSettled: (_data, _error, { contactId }) => {
      void invalidateAfterMutation(
        queryClient,
        { queryKey: contactKeys.detail(contactId) },
        { queryKey: contactKeys.tags(contactId) },
        { queryKey: contactKeys.lists() }
      );
    },
  });
}

export function useCreateTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (attributes: TagCreateAttributes) => createTag(attributes),
    onSuccess: () => {
      void invalidateAfterMutation(queryClient, { queryKey: tagKeys.lists() });
      toast.success(SUCCESS_MESSAGES.TAG_CREATED);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

// Tag Update & Delete API Functions

async function updateTag(
  id: string,
  attributes: Partial<TagCreateAttributes>
): Promise<TagResponse> {
  const response = await fetch(`/api/tags/${id}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      data: {
        type: 'tags',
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

async function deleteTag(id: string): Promise<void> {
  const response = await fetch(`/api/tags/${id}`, {
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

export function useUpdateTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      attributes,
    }: {
      id: string;
      attributes: Partial<TagCreateAttributes>;
    }) => updateTag(id, attributes),
    onSuccess: () => {
      void invalidateAfterMutation(queryClient, { queryKey: tagKeys.lists() });
      toast.success(SUCCESS_MESSAGES.TAG_UPDATED);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

/**
 * Deletes a tag, which also un-assigns it from every contact.
 *
 * The tag namespace and the contact queries are both refreshed: the tag leaves
 * the sidebar tree, and the chips on the contacts list and in any open
 * contact's tag editor go with it.
 *
 * This neither splices the cache by hand nor delays the invalidation behind a
 * timer — the write commits in the service layer before the response is sent,
 * so there is no read-after-write race to wait out (#1204). The cancel that
 * `invalidateAfterMutation` performs is what keeps an in-flight list fetch from
 * settling afterwards with pre-mutation rows (#1203).
 */
export function useDeleteTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => deleteTag(id),
    onSuccess: () => {
      void invalidateAfterMutation(
        queryClient,
        { queryKey: tagKeys.lists() },
        { queryKey: contactKeys.all }
      );
      toast.success(SUCCESS_MESSAGES.TAG_DELETED);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

async function mergeTag(sourceId: string, targetId: string): Promise<void> {
  const response = await fetch(`/api/tags/${sourceId}/merge`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      data: {
        type: 'tags',
        attributes: {
          target_tag_id: Number.parseInt(targetId, 10),
        },
      },
    }),
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(errorData.errors?.[0]?.detail || 'Failed to merge tag');
  }
}

/**
 * Merges a tag into another, deleting the source tag.
 *
 * Contacts tagged with the source end up tagged with the target, so the contact
 * queries are refreshed alongside the tag namespace — immediately, and without
 * a hand-written splice, for the same reasons as {@link useDeleteTag}.
 */
export function useMergeTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      sourceId,
      targetId,
    }: {
      sourceId: string;
      targetId: string;
    }) => mergeTag(sourceId, targetId),
    onSuccess: () => {
      void invalidateAfterMutation(
        queryClient,
        { queryKey: tagKeys.lists() },
        { queryKey: contactKeys.all }
      );
      toast.success('Tag successfully merged');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

// Custom Date Types Actions
export const customDateTypeKeys = {
  all: ['custom-date-types'] as const,
  lists: () => [...customDateTypeKeys.all, 'list'] as const,
};

async function fetchCustomDateTypes(): Promise<CustomDateTypeListResponse> {
  const response = await fetch('/api/custom-date-types', {
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

async function createCustomDateType(
  name: string
): Promise<CustomDateTypeResponse> {
  const requestData = {
    type: 'custom_date_types',
    attributes: { name },
  };

  const response = await fetch('/api/custom-date-types', {
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

export function useCustomDateTypes() {
  return useQuery({
    queryKey: customDateTypeKeys.lists(),
    queryFn: fetchCustomDateTypes,
    staleTime: 10 * 60 * 1000, // 10 minutes
  });
}

export function useCreateCustomDateType() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createCustomDateType,
    onSuccess: () => {
      void invalidateAfterMutation(queryClient, {
        queryKey: customDateTypeKeys.all,
      });
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

// Summary Refresh API Functions

async function refreshContactSummary(contactId: string): Promise<void> {
  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/summary/refresh`,
    {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.UPDATE_FAILED
    );
  }
}

export function useRefreshContactSummary(contactId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => refreshContactSummary(contactId),
    onSuccess: () => {
      void invalidateAfterMutation(queryClient, {
        queryKey: contactKeys.detail(contactId),
      });
      toast.success('Summary refresh requested');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

// Summary Configuration API Functions

export async function updateContactSummary(
  contactId: string,
  data: ContactSummaryUpdateData
): Promise<ContactResponse> {
  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/summary`,
    {
      method: 'PATCH',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ data }),
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

/**
 * Update a contact's AI summary configuration, e.g. turning generation off
 * or back on. Re-enabling queues a new summary on the server.
 */
export function useUpdateContactSummary(contactId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: ContactSummaryUpdateData) =>
      updateContactSummary(contactId, data),
    onSuccess: () => {
      void invalidateAfterMutation(queryClient, {
        queryKey: contactKeys.detail(contactId),
      });
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}
