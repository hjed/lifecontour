/**
 * Contact API client functions using TanStack Query.
 *
 * Provides typed API functions for contact management operations
 * with proper error handling and caching.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  ContactListResponse,
  ContactResponse,
  ContactCreateData,
  ContactUpdateData,
  ContactFormData,
  ContactFilters,
  TagListResponse,
} from '@/types/contacts';
import { JsonApiErrorResponse } from '@/types/api';
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
  details: () => [...contactKeys.all, 'detail'] as const,
  detail: (id: string) => [...contactKeys.details(), id] as const,
  search: (query: string) => [...contactKeys.all, 'search', query] as const,
};

export const tagKeys = {
  all: ['tags'] as const,
  lists: () => [...tagKeys.all, 'list'] as const,
};

// API Functions
export async function fetchContacts(
  filters: ContactFilters = {}
): Promise<ContactListResponse> {
  const params = new URLSearchParams();

  if (filters.search) params.append('search', filters.search);
  if (filters.tags?.length) {
    filters.tags.forEach(tag => {
      // Convert tag to integer ID if it's a string representation
      const tagId = typeof tag === 'string' ? parseInt(tag, 10) : tag;
      if (!isNaN(tagId)) {
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

export function useContact(id: string) {
  return useQuery({
    queryKey: contactKeys.detail(id),
    queryFn: () => fetchContact(id),
    enabled: !!id,
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
    enabled:
      queryOptions.enabled !== undefined
        ? queryOptions.enabled
        : query.length > 0,
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
