/**
 * Contact Relationship API client functions using TanStack Query.
 *
 * Provides typed API functions for contact relationship management operations
 * with proper error handling and caching.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  ContactRelationshipListResponse,
  ContactRelationshipResponse,
  ContactRelationshipCreateData,
  ContactRelationshipUpdateData,
  ContactRelationshipFormData,
} from '@/types/contacts';
import { JsonApiErrorResponse } from '@/types/api';
import {
  API_ENDPOINTS,
  ERROR_MESSAGES,
  SUCCESS_MESSAGES,
} from '@/lib/constants';

// Types for relationship types API
export interface EnumValue {
  value: string;
  display_name: string;
}

export interface RelationshipTypesResponse {
  relationship_types: EnumValue[];
}

/**
 * Helper function to handle API error responses safely
 */
async function handleApiError(
  response: Response,
  defaultMessage: string
): Promise<never> {
  let errorMessage = defaultMessage;
  const contentType = response.headers.get('content-type');

  if (contentType && contentType.includes('application/json')) {
    try {
      const errorData: JsonApiErrorResponse = await response.json();
      errorMessage = errorData.errors?.[0]?.detail || errorMessage;
    } catch {
      // If JSON parsing fails, use default message with status info
      errorMessage = `${defaultMessage} (Status: ${response.status} ${response.statusText})`;
    }
  } else {
    // Non-JSON response, include status info
    errorMessage = `${defaultMessage} (Status: ${response.status} ${response.statusText})`;
  }

  throw new Error(errorMessage);
}

// Query Keys
export const relationshipKeys = {
  all: ['relationships'] as const,
  lists: () => [...relationshipKeys.all, 'list'] as const,
  list: (contactId: string) =>
    [...relationshipKeys.lists(), contactId] as const,
  details: () => [...relationshipKeys.all, 'detail'] as const,
  detail: (contactId: string, relationshipId: string) =>
    [...relationshipKeys.details(), contactId, relationshipId] as const,
};

// API Functions
export async function fetchContactRelationships(
  contactId: string
): Promise<ContactRelationshipListResponse> {
  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BY_ID(contactId)}/relationships`,
    {
      method: 'GET',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
    }
  );

  if (!response.ok) {
    await handleApiError(response, ERROR_MESSAGES.FETCH_FAILED);
  }

  return response.json();
}

export async function fetchContactRelationship(
  contactId: string,
  relationshipId: string
): Promise<ContactRelationshipResponse> {
  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BY_ID(contactId)}/relationships/${relationshipId}`,
    {
      method: 'GET',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
    }
  );

  if (!response.ok) {
    await handleApiError(response, ERROR_MESSAGES.FETCH_FAILED);
  }

  return response.json();
}

async function createContactRelationship(
  contactId: string,
  data: ContactRelationshipFormData
): Promise<ContactRelationshipResponse> {
  const requestData: ContactRelationshipCreateData = {
    type: 'contact_relationships',
    attributes: data,
  };

  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BY_ID(contactId)}/relationships`,
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
    await handleApiError(response, ERROR_MESSAGES.CREATE_FAILED);
  }

  return response.json();
}

async function updateContactRelationship(
  contactId: string,
  relationshipId: string,
  data: ContactRelationshipFormData
): Promise<ContactRelationshipResponse> {
  const requestData: ContactRelationshipUpdateData = {
    type: 'contact_relationships',
    id: relationshipId,
    attributes: data,
  };

  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BY_ID(contactId)}/relationships/${relationshipId}`,
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
    await handleApiError(response, ERROR_MESSAGES.UPDATE_FAILED);
  }

  return response.json();
}

async function deleteContactRelationship(
  contactId: string,
  relationshipId: string
): Promise<void> {
  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BY_ID(contactId)}/relationships/${relationshipId}`,
    {
      method: 'DELETE',
      credentials: 'include',
    }
  );

  if (!response.ok) {
    await handleApiError(response, ERROR_MESSAGES.DELETE_FAILED);
  }
}

// React Query Hooks
export function useContactRelationships(contactId: string) {
  return useQuery({
    queryKey: relationshipKeys.list(contactId),
    queryFn: () => fetchContactRelationships(contactId),
    enabled: !!contactId,
  });
}

export function useContactRelationship(
  contactId: string,
  relationshipId: string
) {
  return useQuery({
    queryKey: relationshipKeys.detail(contactId, relationshipId),
    queryFn: () => fetchContactRelationship(contactId, relationshipId),
    enabled: !!contactId && !!relationshipId,
  });
}

export function useCreateContactRelationship() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      contactId,
      data,
    }: {
      contactId: string;
      data: ContactRelationshipFormData;
    }) => createContactRelationship(contactId, data),
    onSuccess: (_, { contactId }) => {
      queryClient.invalidateQueries({
        queryKey: relationshipKeys.list(contactId),
      });
      queryClient.invalidateQueries({
        queryKey: ['contacts', 'detail', contactId],
      });
      toast.success(SUCCESS_MESSAGES.CREATE_SUCCESS);
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
      contactId,
      relationshipId,
      data,
    }: {
      contactId: string;
      relationshipId: string;
      data: ContactRelationshipFormData;
    }) => updateContactRelationship(contactId, relationshipId, data),
    onSuccess: (_, { contactId, relationshipId }) => {
      queryClient.invalidateQueries({
        queryKey: relationshipKeys.list(contactId),
      });
      queryClient.invalidateQueries({
        queryKey: relationshipKeys.detail(contactId, relationshipId),
      });
      queryClient.invalidateQueries({
        queryKey: ['contacts', 'detail', contactId],
      });
      toast.success(SUCCESS_MESSAGES.UPDATE_SUCCESS);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

export function useDeleteContactRelationship() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      contactId,
      relationshipId,
    }: {
      contactId: string;
      relationshipId: string;
    }) => deleteContactRelationship(contactId, relationshipId),
    onSuccess: (_, { contactId }) => {
      queryClient.invalidateQueries({
        queryKey: relationshipKeys.list(contactId),
      });
      queryClient.invalidateQueries({
        queryKey: ['contacts', 'detail', contactId],
      });
      toast.success(SUCCESS_MESSAGES.DELETE_SUCCESS);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

// Relationship Types API Functions

/**
 * Fetch all available relationship types with display names
 */
export async function fetchRelationshipTypes(): Promise<RelationshipTypesResponse> {
  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BASE}/relationship-types`,
    {
      credentials: 'include',
    }
  );

  if (!response.ok) {
    await handleApiError(response, 'Failed to fetch relationship types');
  }

  return response.json();
}

/**
 * Hook to fetch relationship types
 */
export function useRelationshipTypes() {
  return useQuery({
    queryKey: ['relationship-types'],
    queryFn: fetchRelationshipTypes,
    staleTime: 5 * 60 * 1000, // 5 minutes - enum values don't change often
  });
}
