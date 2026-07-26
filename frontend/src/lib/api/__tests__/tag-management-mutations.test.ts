/**
 * @jest-environment jsdom
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React, { ReactNode } from 'react';
import {
  contactKeys,
  tagKeys,
  useUpdateTag,
  useDeleteTag,
  useMergeTag,
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
    TAG_UPDATED: 'Tag updated successfully',
    TAG_DELETED: 'Tag deleted successfully',
  },
}));

const mockFetch = fetch as jest.MockedFunction<typeof fetch>;
const { toast } = jest.requireMock('sonner') as {
  toast: { success: jest.Mock; error: jest.Mock };
};

interface CachedTagList {
  data: { id: string; type: string; attributes: { name: string } }[];
}

/** A tag list in the cache, where `12` is the tag the tests act on. */
function cachedTagList(): CachedTagList {
  return {
    data: [
      { id: '12', type: 'tags', attributes: { name: 'Subject' } },
      { id: '13', type: 'tags', attributes: { name: 'Bystander' } },
    ],
  };
}

function cachedTagIds(queryClient: QueryClient): string[] {
  const cached = queryClient.getQueryData<CachedTagList>(tagKeys.lists());
  return (cached?.data ?? []).map(tag => tag.id);
}

/** Enough of a jest spy to order its calls against another spy's. */
interface CallOrdered {
  mock: { invocationCallOrder: readonly number[] };
}

function firstCallOrder(spy: CallOrdered): number {
  return Math.min(...spy.mock.invocationCallOrder);
}

function lastCallOrder(spy: CallOrdered): number {
  return Math.max(...spy.mock.invocationCallOrder);
}

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

    it('should invalidate tag and contact queries without waiting out a timer', async () => {
      // Fake timers with nothing advanced: a mutation that deferred its
      // invalidation would leave the callback queued and the spy untouched.
      // The backend commits the delete before it responds, so there is no
      // read-after-write race to wait out.
      jest.useFakeTimers();

      try {
        mockFetch.mockResolvedValueOnce({
          ok: true,
        } as Response);

        const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

        const { result } = renderHook(() => useDeleteTag(), {
          wrapper: createWrapper,
        });

        await act(async () => {
          await result.current.mutateAsync('12');
        });

        expect(invalidateSpy).toHaveBeenCalledWith({
          queryKey: tagKeys.lists(),
        });
        // The deleted tag disappears from the sidebar tree, from the chips on
        // the contacts list and from any open contact's tag editor.
        expect(invalidateSpy).toHaveBeenCalledWith({
          queryKey: contactKeys.all,
        });
      } finally {
        jest.useRealTimers();
      }
    });

    it('should leave the cached tag list to the invalidation rather than splicing it', async () => {
      queryClient.setQueryData(tagKeys.lists(), cachedTagList());

      mockFetch.mockResolvedValueOnce({
        ok: true,
      } as Response);

      const { result } = renderHook(() => useDeleteTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await result.current.mutateAsync('12');
      });

      // Hand-removing the row duplicates what the refetch does and puts the
      // hook in the business of maintaining a server-owned shape.
      expect(cachedTagIds(queryClient)).toEqual(['12', '13']);
      expect(queryClient.getQueryState(tagKeys.lists())?.isInvalidated).toBe(
        true
      );
    });

    it('should cancel the in-flight queries before invalidating them', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
      } as Response);

      const cancelSpy = jest.spyOn(queryClient, 'cancelQueries');
      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useDeleteTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await result.current.mutateAsync('12');
      });

      expect(cancelSpy).toHaveBeenCalledWith({ queryKey: tagKeys.lists() });
      expect(cancelSpy).toHaveBeenCalledWith({ queryKey: contactKeys.all });
      // Both lists carry a five-minute staleTime, so a fetch already in flight
      // when the delete lands would otherwise settle *after* the invalidation
      // with pre-delete rows and be fresh for the next five minutes.
      expect(lastCallOrder(cancelSpy)).toBeLessThan(
        firstCallOrder(invalidateSpy)
      );
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

  describe('useMergeTag', () => {
    it('should POST the target tag to the source tag merge endpoint', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
      } as Response);

      const { result } = renderHook(() => useMergeTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({ sourceId: '12', targetId: '13' });

      // The source is the path parameter and the target travels in the body;
      // the endpoint takes the target as a number, unlike the string ids the
      // rest of the JSON:API surface uses.
      expect(mockFetch).toHaveBeenCalledWith('/api/tags/12/merge', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          data: {
            type: 'tags',
            attributes: { target_tag_id: 13 },
          },
        }),
      });
    });

    it('should invalidate tag and contact queries without waiting out a timer', async () => {
      jest.useFakeTimers();

      try {
        mockFetch.mockResolvedValueOnce({
          ok: true,
        } as Response);

        const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

        const { result } = renderHook(() => useMergeTag(), {
          wrapper: createWrapper,
        });

        await act(async () => {
          await result.current.mutateAsync({ sourceId: '12', targetId: '13' });
        });

        expect(invalidateSpy).toHaveBeenCalledWith({
          queryKey: tagKeys.lists(),
        });
        // Contacts tagged with the source now carry the target instead.
        expect(invalidateSpy).toHaveBeenCalledWith({
          queryKey: contactKeys.all,
        });
      } finally {
        jest.useRealTimers();
      }
    });

    it('should leave the cached tag list to the invalidation rather than splicing it', async () => {
      queryClient.setQueryData(tagKeys.lists(), cachedTagList());

      mockFetch.mockResolvedValueOnce({
        ok: true,
      } as Response);

      const { result } = renderHook(() => useMergeTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await result.current.mutateAsync({ sourceId: '12', targetId: '13' });
      });

      expect(cachedTagIds(queryClient)).toEqual(['12', '13']);
      expect(queryClient.getQueryState(tagKeys.lists())?.isInvalidated).toBe(
        true
      );
    });

    it('should cancel the in-flight queries before invalidating them', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
      } as Response);

      const cancelSpy = jest.spyOn(queryClient, 'cancelQueries');
      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useMergeTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await result.current.mutateAsync({ sourceId: '12', targetId: '13' });
      });

      expect(cancelSpy).toHaveBeenCalledWith({ queryKey: tagKeys.lists() });
      expect(cancelSpy).toHaveBeenCalledWith({ queryKey: contactKeys.all });
      expect(lastCallOrder(cancelSpy)).toBeLessThan(
        firstCallOrder(invalidateSpy)
      );
    });

    it('should show success toast on success', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
      } as Response);

      const { result } = renderHook(() => useMergeTag(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({ sourceId: '12', targetId: '13' });

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith('Tag successfully merged');
      });
    });

    it('should handle API error', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({
          errors: [{ detail: 'Cannot merge a tag into itself' }],
        }),
      } as Response);

      const { result } = renderHook(() => useMergeTag(), {
        wrapper: createWrapper,
      });

      await expect(
        result.current.mutateAsync({ sourceId: '12', targetId: '12' })
      ).rejects.toThrow('Cannot merge a tag into itself');

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith(
          'Cannot merge a tag into itself'
        );
      });
    });
  });
});
