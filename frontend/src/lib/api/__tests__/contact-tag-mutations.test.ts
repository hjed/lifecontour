/**
 * @jest-environment jsdom
 */

import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React, { ReactNode } from 'react';
import {
  contactKeys,
  tagKeys,
  useAssignContactTag,
  useRemoveContactTag,
  useCreateTag,
} from '../contacts';

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
  },
}));

const mockFetch = fetch as jest.MockedFunction<typeof fetch>;
const { toast } = jest.requireMock('sonner') as {
  toast: { success: jest.Mock; error: jest.Mock };
};

describe('Contact Tag Mutation Hooks', () => {
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

  describe('useAssignContactTag', () => {
    it('should send correct POST request to assign a tag', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
      } as Response);

      const { result } = renderHook(() => useAssignContactTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        contactId: '42',
        tagId: '7',
      });

      expect(mockFetch).toHaveBeenCalledWith('/api/contacts/42/tags', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          data: {
            type: 'tags',
            id: '7',
          },
        }),
      });
    });

    it('should invalidate contact detail and tags queries on success', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
      } as Response);

      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useAssignContactTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        contactId: '42',
        tagId: '7',
      });

      await waitFor(() => {
        expect(invalidateSpy).toHaveBeenCalledWith(
          expect.objectContaining({
            queryKey: contactKeys.detail('42'),
          })
        );
        expect(invalidateSpy).toHaveBeenCalledWith(
          expect.objectContaining({
            queryKey: contactKeys.tags('42'),
          })
        );
        expect(invalidateSpy).toHaveBeenCalledWith(
          expect.objectContaining({
            queryKey: contactKeys.lists(),
          })
        );
      });
    });

    it('should show success toast on success', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
      } as Response);

      const { result } = renderHook(() => useAssignContactTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        contactId: '42',
        tagId: '7',
      });

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith('Tag assigned successfully');
      });
    });

    it('should handle API error', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({
          errors: [{ detail: 'Tag already assigned' }],
        }),
      } as Response);

      const { result } = renderHook(() => useAssignContactTag(), {
        wrapper: createWrapper,
      });

      await expect(
        result.current.mutateAsync({
          contactId: '42',
          tagId: '7',
        })
      ).rejects.toThrow('Tag already assigned');

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalled();
      });
    });
  });

  describe('useRemoveContactTag', () => {
    it('should send correct DELETE request to remove a tag', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
      } as Response);

      const { result } = renderHook(() => useRemoveContactTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        contactId: '42',
        tagId: '7',
      });

      expect(mockFetch).toHaveBeenCalledWith('/api/contacts/42/tags/7', {
        method: 'DELETE',
        credentials: 'include',
      });
    });

    it('should invalidate contact detail and tags queries on success', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
      } as Response);

      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useRemoveContactTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        contactId: '42',
        tagId: '7',
      });

      await waitFor(() => {
        expect(invalidateSpy).toHaveBeenCalledWith(
          expect.objectContaining({
            queryKey: contactKeys.detail('42'),
          })
        );
        expect(invalidateSpy).toHaveBeenCalledWith(
          expect.objectContaining({
            queryKey: contactKeys.tags('42'),
          })
        );
        expect(invalidateSpy).toHaveBeenCalledWith(
          expect.objectContaining({
            queryKey: contactKeys.lists(),
          })
        );
      });
    });

    it('should show success toast on success', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
      } as Response);

      const { result } = renderHook(() => useRemoveContactTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        contactId: '42',
        tagId: '7',
      });

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith('Tag removed successfully');
      });
    });

    it('should handle API error', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({
          errors: [{ detail: 'Tag not found on contact' }],
        }),
      } as Response);

      const { result } = renderHook(() => useRemoveContactTag(), {
        wrapper: createWrapper,
      });

      await expect(
        result.current.mutateAsync({
          contactId: '42',
          tagId: '7',
        })
      ).rejects.toThrow('Tag not found on contact');
    });

    it('should optimistically remove the tag from the cache before the request resolves', async () => {
      queryClient.setQueryData(contactKeys.tags('42'), {
        data: [
          { id: '7', type: 'tags', attributes: { name: 'Keep me out' } },
          { id: '8', type: 'tags', attributes: { name: 'Stay' } },
        ],
      });

      // Resolve only when we choose, so we can observe the optimistic state.
      let resolveFetch: (value: Response) => void = () => {};
      mockFetch.mockReturnValueOnce(
        new Promise<Response>(resolve => {
          resolveFetch = resolve;
        })
      );

      const { result } = renderHook(() => useRemoveContactTag(), {
        wrapper: createWrapper,
      });

      result.current.mutate({ contactId: '42', tagId: '7' });

      await waitFor(() => {
        const cached = queryClient.getQueryData(contactKeys.tags('42')) as {
          data: { id: string }[];
        };
        expect(cached.data.map(t => t.id)).toEqual(['8']);
      });

      resolveFetch({ ok: true } as Response);
    });

    it('should roll back the optimistic removal when the request fails', async () => {
      const original = {
        data: [
          { id: '7', type: 'tags', attributes: { name: 'Keep me out' } },
          { id: '8', type: 'tags', attributes: { name: 'Stay' } },
        ],
      };
      queryClient.setQueryData(contactKeys.tags('42'), original);

      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ errors: [{ detail: 'Boom' }] }),
      } as Response);

      const { result } = renderHook(() => useRemoveContactTag(), {
        wrapper: createWrapper,
      });

      await expect(
        result.current.mutateAsync({ contactId: '42', tagId: '7' })
      ).rejects.toThrow('Boom');

      const cached = queryClient.getQueryData(contactKeys.tags('42')) as {
        data: { id: string }[];
      };
      expect(cached.data.map(t => t.id)).toEqual(['7', '8']);
    });
  });

  describe('useCreateTag', () => {
    it('should send correct POST request to create a tag', async () => {
      const mockResponse = {
        data: {
          id: '99',
          type: 'tags',
          attributes: {
            name: 'NewTag',
            color: '#E53E3E',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
          },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(() => useCreateTag(), {
        wrapper: createWrapper,
      });

      const response = await result.current.mutateAsync({
        name: 'NewTag',
        color: '#E53E3E',
      });

      expect(mockFetch).toHaveBeenCalledWith('/api/tags', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          data: {
            type: 'tags',
            attributes: {
              name: 'NewTag',
              color: '#E53E3E',
            },
          },
        }),
      });

      expect(response).toEqual(mockResponse);
    });

    it('should invalidate tags list queries on success', async () => {
      const mockResponse = {
        data: {
          id: '99',
          type: 'tags',
          attributes: {
            name: 'NewTag',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
          },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useCreateTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        name: 'NewTag',
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
            id: '99',
            type: 'tags',
            attributes: {
              name: 'NewTag',
              created_at: '2024-01-01T00:00:00Z',
              updated_at: '2024-01-01T00:00:00Z',
            },
          },
        }),
      } as Response);

      const { result } = renderHook(() => useCreateTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({ name: 'NewTag' });

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith('Tag created successfully');
      });
    });

    it('should handle API error', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({
          errors: [{ detail: 'Tag name already exists' }],
        }),
      } as Response);

      const { result } = renderHook(() => useCreateTag(), {
        wrapper: createWrapper,
      });

      await expect(
        result.current.mutateAsync({ name: 'Duplicate' })
      ).rejects.toThrow('Tag name already exists');
    });

    it('should create tag with only a name (no colour)', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          data: {
            id: '99',
            type: 'tags',
            attributes: {
              name: 'SimpleTag',
              created_at: '2024-01-01T00:00:00Z',
              updated_at: '2024-01-01T00:00:00Z',
            },
          },
        }),
      } as Response);

      const { result } = renderHook(() => useCreateTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({ name: 'SimpleTag' });

      expect(mockFetch).toHaveBeenCalledWith('/api/tags', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          data: {
            type: 'tags',
            attributes: {
              name: 'SimpleTag',
            },
          },
        }),
      });
    });
  });
});
