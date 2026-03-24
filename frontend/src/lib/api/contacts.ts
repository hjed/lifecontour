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
} from '@/types/contacts';
import { JsonApiErrorResponse, JsonApiMeta } from '@/types/api';
import {
  API_ENDPOINTS,
  ERROR_MESSAGES,
  SUCCESS_MESSAGES,
} from '@/lib/constants';

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

async function fetchContact(id: string): Promise<ContactResponse> {
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

  return response.json();
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
  data: ContactFormData
): Promise<ContactResponse> {
  const requestData: ContactUpdateData = {
    type: 'contacts',
    id,
    attributes: data,
  };

  const response = await fetch(API_ENDPOINTS.CONTACTS.BY_ID(id), {
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
  const response = await fetch('/api/tags', {
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
      queryClient.invalidateQueries({ queryKey: contactKeys.all });
      toast.success(SUCCESS_MESSAGES.CONTACT_CREATED);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useUpdateContact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: ContactFormData }) =>
      updateContact(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: contactKeys.detail(id) });
      queryClient.invalidateQueries({ queryKey: contactKeys.lists() });
      toast.success(SUCCESS_MESSAGES.CONTACT_UPDATED);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useDeleteContact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteContact,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: contactKeys.all });
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
      queryClient.invalidateQueries({
        queryKey: contactKeys.detail(contactId),
      });
      queryClient.invalidateQueries({ queryKey: contactKeys.lists() });
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

// Field-level update functions
export async function updateContactField(
  contactId: string,
  fieldName: string,
  value: string
): Promise<ContactResponse> {
  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/fields/${fieldName}`,
    {
      method: 'PATCH',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        data: {
          type: 'contact_fields',
          attributes: {
            value,
          },
        },
      }),
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    const errorMessage =
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.UPDATE_FAILED;
    throw new Error(errorMessage);
  }

  return response.json();
}

export function useUpdateContactField() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      contactId,
      fieldName,
      value,
    }: {
      contactId: string;
      fieldName: string;
      value: string;
    }) => updateContactField(contactId, fieldName, value),
    onSuccess: (data, variables) => {
      const contactId = variables.contactId;
      queryClient.invalidateQueries({
        queryKey: contactKeys.detail(contactId),
      });
      queryClient.invalidateQueries({ queryKey: contactKeys.lists() });
    },
    onError: (error: Error) => {
      // Don't show toast here - let the component handle it
      console.error('Field update failed:', error);
    },
  });
}

// Contact History API Functions
export const historyKeys = {
  all: ['contact-history'] as const,
  list: (contactId: string, page?: number, limit?: number) =>
    [...historyKeys.all, contactId, { page, limit }] as const,
};

export interface HistoryFilters {
  page?: number;
  limit?: number;
}

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
    queryFn: () => fetchContactHistory(contactId, filters),
    enabled: options.enabled !== false && !!contactId,
    staleTime: 2 * 60 * 1000, // 2 minutes for history
  });
}

// Contact Methods Management API Functions

export async function updateContactMethodField(
  contactId: string,
  methodId: string,
  fieldName: string,
  value: string
): Promise<void> {
  const requestData = {
    type: 'contact_method_fields',
    attributes: { value },
  };

  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/methods/${methodId}/fields/${fieldName}`,
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
}

export async function updateContactAddressField(
  contactId: string,
  addressId: string,
  fieldName: string,
  value: string
): Promise<void> {
  const requestData = {
    type: 'contact_address_fields',
    attributes: { value },
  };

  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/addresses/${addressId}/fields/${fieldName}`,
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
}

async function addContactMethod(
  contactId: string,
  method: ContactMethodAttributes
): Promise<ContactResponse> {
  const requestData = {
    type: 'contact_methods',
    attributes: method,
  };

  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/methods`,
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

async function deleteContactMethod(
  contactId: string,
  methodId: string
): Promise<void> {
  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/methods/${methodId}`,
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

// Contact Addresses Management API Functions

async function addContactAddress(
  contactId: string,
  address: ContactAddressAttributes
): Promise<ContactResponse> {
  const requestData = {
    type: 'contact_addresses',
    attributes: address,
  };

  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/addresses`,
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

async function deleteContactAddress(
  contactId: string,
  addressId: string
): Promise<void> {
  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BASE}/${contactId}/addresses/${addressId}`,
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

// React Query Hooks for Contact Methods

export function useAddContactMethod() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      contactId,
      method,
    }: {
      contactId: string;
      method: ContactMethodAttributes;
    }) => addContactMethod(contactId, method),
    onSuccess: (_, { contactId }) => {
      queryClient.invalidateQueries({
        queryKey: contactKeys.detail(contactId),
      });
      queryClient.invalidateQueries({ queryKey: contactKeys.lists() });
      toast.success('Contact method added successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useDeleteContactMethod() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      contactId,
      methodId,
    }: {
      contactId: string;
      methodId: string;
    }) => deleteContactMethod(contactId, methodId),
    onSuccess: (_, { contactId }) => {
      queryClient.invalidateQueries({
        queryKey: contactKeys.detail(contactId),
      });
      queryClient.invalidateQueries({ queryKey: contactKeys.lists() });
      toast.success('Contact method deleted successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

// React Query Hooks for Contact Addresses

export function useAddContactAddress() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      contactId,
      address,
    }: {
      contactId: string;
      address: ContactAddressAttributes;
    }) => addContactAddress(contactId, address),
    onSuccess: (_, { contactId }) => {
      queryClient.invalidateQueries({
        queryKey: contactKeys.detail(contactId),
      });
      queryClient.invalidateQueries({ queryKey: contactKeys.lists() });
      toast.success('Contact address added successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useDeleteContactAddress() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      contactId,
      addressId,
    }: {
      contactId: string;
      addressId: string;
    }) => deleteContactAddress(contactId, addressId),
    onSuccess: (_, { contactId }) => {
      queryClient.invalidateQueries({
        queryKey: contactKeys.detail(contactId),
      });
      queryClient.invalidateQueries({ queryKey: contactKeys.lists() });
      toast.success('Contact address deleted successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}
