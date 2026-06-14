/**
 * @jest-environment jsdom
 */

import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React, { ReactNode } from 'react';
import { contactKeys, useMergeContact } from '../contacts';

// Mock fetch
globalThis.fetch = jest.fn();

// Mock toast
jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

// Mock constants
jest.mock('@/lib/constants', () => ({
  API_ENDPOINTS: {
    CONTACTS: {
      BASE: '/api/contacts',
      BY_ID: (id: string) => `/api/contacts/${id}`,
    },
    SEARCH: {
      CONTACTS: '/api/search/contacts',
    },
  },
  ERROR_MESSAGES: {
    FETCH_FAILED: 'Failed to fetch data',
    CREATE_FAILED: 'Failed to create item',
    UPDATE_FAILED: 'Failed to update item',
    DELETE_FAILED: 'Failed to delete item',
    SEARCH_FAILED: 'Search failed',
  },
  SUCCESS_MESSAGES: {
    CONTACT_CREATED: 'Contact created successfully',
    CONTACT_UPDATED: 'Contact updated successfully',
    CONTACT_DELETED: 'Contact deleted successfully',
  },
}));

const mockFetch = fetch as jest.MockedFunction<typeof fetch>;
const { toast } = jest.requireMock('sonner') as {
  toast: { success: jest.Mock; error: jest.Mock };
};

const survivorResponse = {
  data: {
    id: '10',
    type: 'contacts',
    attributes: {
      first_name: 'Survivor',
      last_name: 'Person',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    },
  },
};

describe('useMergeContact', () => {
  let queryClient: QueryClient;

  const createWrapper = ({ children }: { children: ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    jest.clearAllMocks();
  });

  it('POSTs to the survivor merge endpoint with the source id and overrides', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => survivorResponse,
    } as Response);

    const { result } = renderHook(() => useMergeContact(), {
      wrapper: createWrapper,
    });

    const response = await result.current.mutateAsync({
      survivorId: '10',
      sourceId: '20',
      overrides: { first_name: 'Custom', is_favourite: false },
    });

    expect(mockFetch).toHaveBeenCalledWith('/api/contacts/10/merge', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        data: {
          type: 'contact-merge',
          attributes: {
            source_contact_id: 20,
            overrides: { first_name: 'Custom', is_favourite: false },
          },
        },
      }),
    });

    expect(response).toEqual(survivorResponse);
  });

  it('omits the overrides key when no overrides are provided', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => survivorResponse,
    } as Response);

    const { result } = renderHook(() => useMergeContact(), {
      wrapper: createWrapper,
    });

    await result.current.mutateAsync({ survivorId: '10', sourceId: '20' });

    expect(mockFetch).toHaveBeenCalledWith('/api/contacts/10/merge', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        data: {
          type: 'contact-merge',
          attributes: { source_contact_id: 20 },
        },
      }),
    });
  });

  it('invalidates all contacts and both detail caches on success', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => survivorResponse,
    } as Response);

    const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

    const { result } = renderHook(() => useMergeContact(), {
      wrapper: createWrapper,
    });

    await result.current.mutateAsync({ survivorId: '10', sourceId: '20' });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: contactKeys.all })
      );
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: contactKeys.detail('10') })
      );
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: contactKeys.detail('20') })
      );
    });
    expect(toast.success).toHaveBeenCalledWith('Contacts merged successfully');
  });

  it('surfaces the API error detail via an error toast', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({
        errors: [{ detail: 'Cannot merge a contact with itself' }],
      }),
    } as Response);

    const { result } = renderHook(() => useMergeContact(), {
      wrapper: createWrapper,
    });

    await expect(
      result.current.mutateAsync({ survivorId: '10', sourceId: '10' })
    ).rejects.toThrow('Cannot merge a contact with itself');

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        'Cannot merge a contact with itself'
      );
    });
  });
});
