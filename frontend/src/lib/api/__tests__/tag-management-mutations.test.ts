/**
 * @jest-environment jsdom
 */

import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React, { ReactNode } from 'react';
import { contactKeys, tagKeys, useUpdateTag, useDeleteTag } from '../contacts';

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
    TAG_ASSIGNED: 'Tag assigned successfully',
    TAG_REMOVED: 'Tag removed successfully',
    TAG_CREATED: 'Tag created successfully',
    TAG_UPDATED: 'Tag updated successfully',
    TAG_DELETED: 'Tag deleted successfully',
  },
}));

const mockFetch = fetch as jest.MockedFunction<typeof fetch>;
const { toast } = jest.requireMock('sonner') as {
  toast: { success: jest.Mock; error: jest.Mock };
};

describe('Tag Management Mutation Hooks', () => {
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

  describe('useUpdateTag', () => {
    it('should send correct PATCH request to update a tag', async () => {
      const mockResponse = {
        data: {
          id: '5',
          type: 'tags',
          attributes: {
            name: 'UpdatedTag',
            color: '#38A169',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-02T00:00:00Z',
          },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(() => useUpdateTag(), {
        wrapper: createWrapper,
      });

      const response = await result.current.mutateAsync({
        id: '5',
        attributes: {
          name: 'UpdatedTag',
          color: '#38A169',
        },
      });

      expect(mockFetch).toHaveBeenCalledWith('/api/tags/5', {
        method: 'PATCH',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          data: {
            type: 'tags',
            id: '5',
            attributes: {
              name: 'UpdatedTag',
              color: '#38A169',
            },
          },
        }),
      });

      expect(response).toEqual(mockResponse);
    });

    it('should invalidate tag list queries on success', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          data: {
            id: '5',
            type: 'tags',
            attributes: {
              name: 'Updated',
              created_at: '2024-01-01T00:00:00Z',
              updated_at: '2024-01-02T00:00:00Z',
            },
          },
        }),
      } as Response);

      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useUpdateTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        id: '5',
        attributes: { name: 'Updated' },
      });

      await waitFor(() => {
        expect(invalidateSpy).toHaveBeenCalledWith(
          expect.objectContaining({
            queryKey: tagKeys.lists(),
          })
        );
      });
    });

    it('should show success toast on success', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          data: {
            id: '5',
            type: 'tags',
            attributes: {
              name: 'Updated',
              created_at: '2024-01-01T00:00:00Z',
              updated_at: '2024-01-02T00:00:00Z',
            },
          },
        }),
      } as Response);

      const { result } = renderHook(() => useUpdateTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        id: '5',
        attributes: { name: 'Updated' },
      });

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith('Tag updated successfully');
      });
    });

    it('should handle API error', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({
          errors: [{ detail: 'Tag name already exists' }],
        }),
      } as Response);

      const { result } = renderHook(() => useUpdateTag(), {
        wrapper: createWrapper,
      });

      await expect(
        result.current.mutateAsync({
          id: '5',
          attributes: { name: 'Duplicate' },
        })
      ).rejects.toThrow('Tag name already exists');
    });

    it('should update parent_id for re-parenting', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          data: {
            id: '5',
            type: 'tags',
            attributes: {
              name: 'ChildTag',
              parent_id: 10,
              created_at: '2024-01-01T00:00:00Z',
              updated_at: '2024-01-02T00:00:00Z',
            },
          },
        }),
      } as Response);

      const { result } = renderHook(() => useUpdateTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        id: '5',
        attributes: { parent_id: 10 },
      });

      expect(mockFetch).toHaveBeenCalledWith('/api/tags/5', {
        method: 'PATCH',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          data: {
            type: 'tags',
            id: '5',
            attributes: {
              parent_id: 10,
            },
          },
        }),
      });
    });
  });

  describe('useDeleteTag', () => {
    it('should send correct DELETE request', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
      } as Response);

      const { result } = renderHook(() => useDeleteTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync('12');

      expect(mockFetch).toHaveBeenCalledWith('/api/tags/12', {
        method: 'DELETE',
        credentials: 'include',
      });
    });

    it('should invalidate tag and contact queries on success', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
      } as Response);

      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useDeleteTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync('12');

      await waitFor(() => {
        expect(invalidateSpy).toHaveBeenCalledWith(
          expect.objectContaining({
            queryKey: tagKeys.lists(),
          })
        );
        expect(invalidateSpy).toHaveBeenCalledWith(
          expect.objectContaining({
            queryKey: contactKeys.all,
          })
        );
      });
    });

    it('should show success toast on success', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
      } as Response);

      const { result } = renderHook(() => useDeleteTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync('12');

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith('Tag deleted successfully');
      });
    });

    it('should handle API error', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({
          errors: [{ detail: 'Tag is still in use' }],
        }),
      } as Response);

      const { result } = renderHook(() => useDeleteTag(), {
        wrapper: createWrapper,
      });

      await expect(result.current.mutateAsync('12')).rejects.toThrow(
        'Tag is still in use'
      );
    });
  });
});
