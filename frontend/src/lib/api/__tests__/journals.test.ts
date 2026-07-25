/**
 * @jest-environment jsdom
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React, { ReactNode } from 'react';
import {
  useJournals,
  useJournal,
  useSearchJournals,
  useJournalTags,
  useCreateJournalTag,
  useUpdateJournalTag,
  useAddJournalTag,
  useRemoveJournalTag,
  journalTagKeys,
  useCreateJournal,
  useUpdateJournal,
  useDeleteJournal,
  useContactJournals,
  useCalendars,
  useCreateCalendar,
  useUpdateCalendar,
  useDeleteCalendar,
  useInfiniteJournals,
  useDismissReviewItem,
  journalKeys,
  reviewItemKeys,
} from '../journals';
import { JournalType } from '@/types/journals';
import { toast } from 'sonner';

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
    JOURNALS: {
      BASE: '/api/journals',
      BY_ID: (id: string) => `/api/journals/${id}`,
      SEARCH: '/api/journals/search',
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
    JOURNAL_CREATED: 'Journal created successfully',
    JOURNAL_UPDATED: 'Journal updated successfully',
    JOURNAL_DELETED: 'Journal deleted successfully',
    TAG_UPDATED: 'Tag updated successfully',
  },
}));

const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

// Test data factories
const createMockJournalAttributes = (overrides = {}) => ({
  title: 'Test Journal',
  content: 'Test content',
  event_date_range: {
    start: '2024-01-01',
    end: '2024-01-01',
  },
  types: [JournalType.NOTE],
  tags: [],
  contacts: [],
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  ...overrides,
});

const createMockJournal = (id: string, attributeOverrides = {}) => ({
  id,
  type: 'journals' as const,
  attributes: createMockJournalAttributes(attributeOverrides),
});

const createMockJournalListResponse = (
  journals: ReturnType<typeof createMockJournal>[],
  meta: {
    total?: number;
    page?: number;
    per_page?: number;
    total_pages?: number;
  } = {}
) => ({
  data: journals,
  meta: {
    total: journals.length,
    page: 1,
    per_page: 20,
    total_pages: 1,
    ...meta,
  },
});

const createMockJournalResponse = (
  journal: ReturnType<typeof createMockJournal>
) => ({
  data: journal,
});

describe('Journals API', () => {
  let queryClient: QueryClient;

  const createWrapper = ({ children }: { children: ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
        mutations: {
          retry: false,
        },
      },
    });
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  describe('useJournals', () => {
    it('should fetch journals successfully', async () => {
      const mockResponse = createMockJournalListResponse([
        createMockJournal('1'),
      ]);

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(() => useJournals(), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(result.current.data?.data).toHaveLength(1);
      expect(result.current.data?.data[0].attributes.title).toBe(
        'Test Journal'
      );
    });

    it('should apply filters to query', async () => {
      const filters = {
        search: 'test',
        types: [JournalType.NOTE, JournalType.EVENT],
        contact_id: 'contact-1',
        tag_ids: ['tag-1', 'tag-2'],
        date_from: '2024-01-01',
        date_to: '2024-12-31',
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ data: [], meta: {} }),
      } as Response);

      renderHook(() => useJournals(filters), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      // Backend expects singular 'type' and 'start_date'/'end_date', and a
      // repeatable 'tag_ids' param (one entry per selected tag).
      const expectedUrl =
        '/api/journals?search=test&type=note&contact_id=contact-1&tag_ids=tag-1&tag_ids=tag-2&start_date=2024-01-01&end_date=2024-12-31';
      expect(mockFetch).toHaveBeenCalledWith(expectedUrl, expect.any(Object));
    });

    it('should send every selected tag as a repeated tag_ids param', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ data: [], meta: {} }),
      } as Response);

      renderHook(() => useJournals({ tag_ids: ['tag-a', 'tag-b', 'tag-c'] }), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      const url = new URL(
        mockFetch.mock.calls[0][0] as string,
        'http://localhost'
      );
      expect(url.searchParams.getAll('tag_ids')).toEqual([
        'tag-a',
        'tag-b',
        'tag-c',
      ]);
    });

    it('should send a single tag as tag_ids, not the legacy tag_id param', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ data: [], meta: {} }),
      } as Response);

      renderHook(() => useJournals({ tag_ids: ['tag-only'] }), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      const url = new URL(
        mockFetch.mock.calls[0][0] as string,
        'http://localhost'
      );
      expect(url.searchParams.getAll('tag_ids')).toEqual(['tag-only']);
      expect(url.searchParams.has('tag_id')).toBe(false);
    });

    it('should omit tag params entirely when no tags are selected', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ data: [], meta: {} }),
      } as Response);

      renderHook(() => useJournals({ tag_ids: [], search: 'x' }), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      const requestedUrl = mockFetch.mock.calls[0][0] as string;
      expect(requestedUrl).not.toContain('tag_ids');
      expect(requestedUrl).not.toContain('tag_id');
    });

    it('should handle fetch error', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({
          errors: [{ detail: 'Failed to fetch journals' }],
        }),
      } as Response);

      const { result } = renderHook(() => useJournals(), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isError).toBe(true);
      });

      expect(result.current.error).toBeTruthy();
    });

    it('should use the fetch fallback error when list detail is missing', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ errors: [{}] }),
      } as Response);

      const { result } = renderHook(() => useJournals(), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isError).toBe(true);
      });

      expect(result.current.error).toEqual(new Error('Failed to fetch data'));
    });
  });

  describe('useJournal', () => {
    it('should fetch single journal successfully', async () => {
      const mockResponse = createMockJournalResponse(createMockJournal('1'));

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(() => useJournal('1'), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(result.current.data?.data.id).toBe('1');
      expect(result.current.data?.data.attributes.title).toBe('Test Journal');
    });

    it('should use the fetch fallback error when detail is missing', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ errors: [{}] }),
      } as Response);

      const { result } = renderHook(() => useJournal('1'), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isError).toBe(true);
      });

      expect(result.current.error).toEqual(new Error('Failed to fetch data'));
    });
  });

  describe('useSearchJournals', () => {
    it('should search journals successfully', async () => {
      const mockResponse = createMockJournalListResponse([
        createMockJournal('1', {
          title: 'Matching Journal',
          content: 'Content',
        }),
      ]);

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(() => useSearchJournals('test'), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(result.current.data?.data).toHaveLength(1);
    });

    it('should not search with empty query by default', async () => {
      const { result } = renderHook(() => useSearchJournals(''), {
        wrapper: createWrapper,
      });

      expect(result.current.fetchStatus).toBe('idle');
      expect(mockFetch).not.toHaveBeenCalled();
    });
  });

  describe('useJournalTags', () => {
    it('should fetch journal tags successfully', async () => {
      const mockResponse = {
        data: [
          {
            id: '1',
            type: 'journal-tags',
            attributes: { name: 'Tag 1', color: '#FF0000', parent_id: null },
          },
          {
            id: '2',
            type: 'journal-tags',
            attributes: { name: 'Tag 2', color: '#00FF00', parent_id: '1' },
          },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(() => useJournalTags(), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(result.current.data?.data).toHaveLength(2);
      expect(result.current.data?.data[0]).toEqual({
        id: '1',
        name: 'Tag 1',
        color: '#FF0000',
        description: null,
        parent_id: null,
      });
      // Hierarchy is preserved so the editor can render the parent path
      expect(result.current.data?.data[1].parent_id).toBe('1');
    });

    it('should map the tag description so the edit dialog can show it', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          data: [
            {
              id: '1',
              type: 'journal-tags',
              attributes: {
                name: 'Tag 1',
                color: '#FF0000',
                description: 'Outdoor entries',
                parent_id: null,
              },
            },
          ],
        }),
      } as Response);

      const { result } = renderHook(() => useJournalTags(), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(result.current.data?.data[0].description).toBe('Outdoor entries');
    });
  });

  describe('useCreateJournalTag', () => {
    it('should POST a journal-tags resource and return the created id', async () => {
      const mockResponse = {
        data: {
          id: 'new-tag-id',
          type: 'journal-tags',
          attributes: { name: 'Holiday', color: '#DD6B20', parent_id: null },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(() => useCreateJournalTag(), {
        wrapper: createWrapper,
      });

      let created: Awaited<ReturnType<typeof result.current.mutateAsync>>;
      await act(async () => {
        created = await result.current.mutateAsync({
          name: 'Holiday',
          color: '#DD6B20',
        });
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/journals/tags',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            data: {
              type: 'journal-tags',
              attributes: { name: 'Holiday', color: '#DD6B20' },
            },
          }),
        })
      );
      expect(created!.data.id).toBe('new-tag-id');
    });

    it('should throw the JSON:API error detail on failure', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ errors: [{ detail: 'Name already exists' }] }),
      } as Response);

      const { result } = renderHook(() => useCreateJournalTag(), {
        wrapper: createWrapper,
      });

      await expect(
        result.current.mutateAsync({ name: 'Dup', color: '#DD6B20' })
      ).rejects.toThrow('Name already exists');
    });

    it('should invalidate the journal tag list on success', async () => {
      const mockResponse = {
        data: {
          id: 'new-tag-id',
          type: 'journal-tags',
          attributes: { name: 'Holiday', color: '#DD6B20', parent_id: null },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useCreateJournalTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await result.current.mutateAsync({ name: 'Holiday', color: '#DD6B20' });
      });

      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: journalTagKeys.lists(),
      });
      // A new tag can appear in any open journal's tag editor, so the journal
      // queries are refreshed alongside the tag list.
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: journalKeys.all,
      });
    });
  });

  describe('useUpdateJournalTag', () => {
    const updatedTagResponse = {
      data: {
        id: 'tag-1',
        type: 'journal-tags',
        attributes: {
          name: 'Bouldering',
          color: '#38A169',
          description: 'Indoor bouldering',
          parent_id: 'parent-1',
        },
      },
    };

    it('should PATCH the journal-tags resource with the supplied attributes', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => updatedTagResponse,
      } as Response);

      const { result } = renderHook(() => useUpdateJournalTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await result.current.mutateAsync({
          id: 'tag-1',
          attributes: {
            name: 'Bouldering',
            color: '#38A169',
            description: 'Indoor bouldering',
            parent_id: 'parent-1',
          },
        });
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/journals/tags/tag-1',
        expect.objectContaining({
          method: 'PATCH',
          body: JSON.stringify({
            data: {
              type: 'journal-tags',
              id: 'tag-1',
              attributes: {
                name: 'Bouldering',
                color: '#38A169',
                description: 'Indoor bouldering',
                parent_id: 'parent-1',
              },
            },
          }),
        })
      );
    });

    it('should send an explicit null parent_id to move a tag to the root', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => updatedTagResponse,
      } as Response);

      const { result } = renderHook(() => useUpdateJournalTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await result.current.mutateAsync({
          id: 'tag-1',
          attributes: { name: 'Bouldering', parent_id: null },
        });
      });

      const body = JSON.parse(
        (mockFetch.mock.calls[0][1] as RequestInit).body as string
      );
      expect(body.data.attributes).toHaveProperty('parent_id', null);
    });

    it('should invalidate both the tag list and the journal queries on success', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => updatedTagResponse,
      } as Response);

      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useUpdateJournalTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await result.current.mutateAsync({
          id: 'tag-1',
          attributes: { name: 'Bouldering' },
        });
      });

      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: journalTagKeys.lists(),
      });
      // A rename or recolour changes the chips rendered on the journals list
      // and on any open journal detail page.
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: journalKeys.all,
      });
    });

    it('should show a success toast on success', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => updatedTagResponse,
      } as Response);

      const { result } = renderHook(() => useUpdateJournalTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await result.current.mutateAsync({
          id: 'tag-1',
          attributes: { name: 'Bouldering' },
        });
      });

      expect(toast.success).toHaveBeenCalledWith('Tag updated successfully');
    });

    it('should surface the API error to the user as a toast', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({
          errors: [{ detail: 'Tag name already exists' }],
        }),
      } as Response);

      const { result } = renderHook(() => useUpdateJournalTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await expect(
          result.current.mutateAsync({
            id: 'tag-1',
            attributes: { name: 'Duplicate' },
          })
        ).rejects.toThrow('Tag name already exists');
      });

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Tag name already exists');
      });
    });
  });

  describe('useAddJournalTag', () => {
    it('should POST the tag assignment to the journal relationships endpoint', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ data: {} }),
      } as Response);

      const { result } = renderHook(() => useAddJournalTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await result.current.mutateAsync({
          journalId: 'journal-1',
          tagId: 'tag-1',
        });
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/journals/journal-1/relationships/tags',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            data: { type: 'journal-tag', attributes: { tag_id: 'tag-1' } },
          }),
        })
      );
    });

    it('should invalidate the journal detail and list queries on success', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ data: {} }),
      } as Response);

      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useAddJournalTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await result.current.mutateAsync({
          journalId: 'journal-1',
          tagId: 'tag-1',
        });
      });

      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: journalKeys.detail('journal-1'),
      });
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: journalKeys.lists(),
      });
    });

    it('should show a success toast on success', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ data: {} }),
      } as Response);

      const { result } = renderHook(() => useAddJournalTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await result.current.mutateAsync({
          journalId: 'journal-1',
          tagId: 'tag-1',
        });
      });

      expect(toast.success).toHaveBeenCalledWith('Tag added successfully');
    });

    it('should surface the API error to the user as a toast', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ errors: [{ detail: 'Tag not found' }] }),
      } as Response);

      const { result } = renderHook(() => useAddJournalTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await expect(
          result.current.mutateAsync({
            journalId: 'journal-1',
            tagId: 'missing',
          })
        ).rejects.toThrow('Tag not found');
      });

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Tag not found');
      });
    });
  });

  describe('useRemoveJournalTag', () => {
    it('should DELETE the tag assignment from the journal relationships endpoint', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ data: {} }),
      } as Response);

      const { result } = renderHook(() => useRemoveJournalTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await result.current.mutateAsync({
          journalId: 'journal-1',
          tagId: 'tag-1',
        });
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/journals/journal-1/relationships/tags/tag-1',
        expect.objectContaining({ method: 'DELETE' })
      );
    });

    it('should invalidate the journal detail and list queries on success', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ data: {} }),
      } as Response);

      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useRemoveJournalTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await result.current.mutateAsync({
          journalId: 'journal-1',
          tagId: 'tag-1',
        });
      });

      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: journalKeys.detail('journal-1'),
      });
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: journalKeys.lists(),
      });
    });

    it('should show a success toast on success', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ data: {} }),
      } as Response);

      const { result } = renderHook(() => useRemoveJournalTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await result.current.mutateAsync({
          journalId: 'journal-1',
          tagId: 'tag-1',
        });
      });

      expect(toast.success).toHaveBeenCalledWith('Tag removed successfully');
    });

    it('should surface the API error to the user as a toast', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ errors: [{ detail: 'Assignment not found' }] }),
      } as Response);

      const { result } = renderHook(() => useRemoveJournalTag(), {
        wrapper: createWrapper,
      });

      await act(async () => {
        await expect(
          result.current.mutateAsync({
            journalId: 'journal-1',
            tagId: 'missing',
          })
        ).rejects.toThrow('Assignment not found');
      });

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Assignment not found');
      });
    });
  });

  describe('useCreateJournal', () => {
    it('should create journal successfully', async () => {
      const mockResponse = createMockJournalResponse(
        createMockJournal('1', { title: 'New Journal', content: 'Content' })
      );

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(() => useCreateJournal(), {
        wrapper: createWrapper,
      });

      const formData = {
        title: 'New Journal',
        content: 'Content',
        event_date_range: {
          start: '2024-01-01',
          end: '2024-01-01',
        },
      };

      result.current.mutate(formData);

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/journals',
        expect.objectContaining({
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
        })
      );
    });
  });

  describe('useUpdateJournal', () => {
    it('should update journal successfully', async () => {
      const mockResponse = createMockJournalResponse(
        createMockJournal('1', {
          title: 'Updated Journal',
          content: 'Updated content',
          updated_at: '2024-01-02T00:00:00Z',
        })
      );

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(() => useUpdateJournal(), {
        wrapper: createWrapper,
      });

      result.current.mutate({
        id: '1',
        data: { title: 'Updated Journal' },
      });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/journals/1',
        expect.objectContaining({
          method: 'PATCH',
        })
      );
    });
  });

  describe('useDeleteJournal', () => {
    it('should delete journal successfully', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({}),
      } as Response);

      const { result } = renderHook(() => useDeleteJournal(), {
        wrapper: createWrapper,
      });

      result.current.mutate('1');

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/journals/1',
        expect.objectContaining({
          method: 'DELETE',
        })
      );
    });
  });

  describe('useContactJournals', () => {
    it('should fetch journals for a contact', async () => {
      const mockJournals = [
        createMockJournal('1', { title: 'Journal 1' }),
        createMockJournal('2', { title: 'Journal 2' }),
      ];
      const mockResponse = createMockJournalListResponse(mockJournals);

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(() => useContactJournals('123'), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(result.current.data).toEqual(mockResponse);
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/contacts/123/journals?page=1&limit=20',
        expect.objectContaining({
          credentials: 'include',
        })
      );
    });

    it('should filter by relationship type', async () => {
      const mockJournals = [createMockJournal('1')];
      const mockResponse = createMockJournalListResponse(mockJournals);

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(
        () => useContactJournals('123', { relationship_type: 'PARTICIPANT' }),
        { wrapper: createWrapper }
      );

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/contacts/123/journals?page=1&limit=20&relationship_type=PARTICIPANT',
        expect.objectContaining({
          credentials: 'include',
        })
      );
    });

    it('should handle pagination', async () => {
      const mockJournals = [createMockJournal('1')];
      const mockResponse = createMockJournalListResponse(mockJournals);

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(
        () => useContactJournals('123', { page: 2, limit: 10 }),
        { wrapper: createWrapper }
      );

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/contacts/123/journals?page=2&limit=10',
        expect.objectContaining({
          credentials: 'include',
        })
      );
    });

    it('should handle errors', async () => {
      const mockError = {
        errors: [{ detail: 'Contact not found' }],
      };

      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => mockError,
      } as Response);

      const { result } = renderHook(() => useContactJournals('999'), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isError).toBe(true);
      });

      expect(result.current.error).toEqual(new Error('Contact not found'));
    });

    it('should use the fetch fallback error when detail is missing', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ errors: [{}] }),
      } as Response);

      const { result } = renderHook(() => useContactJournals('123'), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isError).toBe(true);
      });

      expect(result.current.error).toEqual(new Error('Failed to fetch data'));
    });
  });

  describe('Calendar Hooks', () => {
    describe('useCalendars', () => {
      it('should fetch calendars successfully', async () => {
        const mockResponse = {
          data: [{ id: '1', attributes: { name: 'Cal 1', color: '#000000' } }],
        };

        mockFetch.mockResolvedValueOnce({
          ok: true,
          json: async () => mockResponse,
        } as Response);

        const { result } = renderHook(() => useCalendars(), {
          wrapper: createWrapper,
        });
        await waitFor(() => {
          expect(result.current.isSuccess).toBe(true);
        });

        expect(result.current.data?.data).toHaveLength(1);
        expect(mockFetch).toHaveBeenCalledWith(
          '/api/calendars',
          expect.any(Object)
        );
      });
    });

    describe('useCreateCalendar', () => {
      it('should create calendar successfully', async () => {
        mockFetch.mockResolvedValueOnce({
          ok: true,
          json: async () => ({ data: { id: '1' } }),
        } as Response);

        const { result } = renderHook(() => useCreateCalendar(), {
          wrapper: createWrapper,
        });
        result.current.mutate({ name: 'New Cal', color: '#ff0000' });

        await waitFor(() => {
          expect(result.current.isSuccess).toBe(true);
        });
        expect(mockFetch).toHaveBeenCalledWith(
          '/api/calendars',
          expect.objectContaining({ method: 'POST' })
        );
      });

      it('should use the create fallback error when detail is missing', async () => {
        mockFetch.mockResolvedValueOnce({
          ok: false,
          json: async () => ({ errors: [{}] }),
        } as Response);

        const { result } = renderHook(() => useCreateCalendar(), {
          wrapper: createWrapper,
        });
        result.current.mutate({ name: 'New Cal', color: '#ff0000' });

        await waitFor(() => {
          expect(result.current.isError).toBe(true);
        });

        expect(result.current.error).toEqual(
          new Error('Failed to create item')
        );
      });
    });

    describe('useUpdateCalendar', () => {
      it('should update calendar successfully', async () => {
        mockFetch.mockResolvedValueOnce({
          ok: true,
          json: async () => ({ data: { id: '1' } }),
        } as Response);

        const { result } = renderHook(() => useUpdateCalendar(), {
          wrapper: createWrapper,
        });
        result.current.mutate({ id: '1', data: { name: 'Updated Cal' } });

        await waitFor(() => {
          expect(result.current.isSuccess).toBe(true);
        });
        expect(mockFetch).toHaveBeenCalledWith(
          '/api/calendars/1',
          expect.objectContaining({ method: 'PUT' })
        );
      });
    });

    describe('useDeleteCalendar', () => {
      it('should delete calendar successfully', async () => {
        mockFetch.mockResolvedValueOnce({
          ok: true,
          json: async () => ({}),
        } as Response);

        const { result } = renderHook(() => useDeleteCalendar(), {
          wrapper: createWrapper,
        });
        result.current.mutate('1');

        await waitFor(() => {
          expect(result.current.isSuccess).toBe(true);
        });
        expect(mockFetch).toHaveBeenCalledWith(
          '/api/calendars/1',
          expect.objectContaining({ method: 'DELETE' })
        );
      });
    });
  });

  describe('useInfiniteJournals', () => {
    it('should use a distinct query key from useJournals for the same filters', async () => {
      const filters = {};

      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => createMockJournalListResponse([]),
      } as Response);

      const { result: standardResult } = renderHook(
        () => useJournals(filters),
        { wrapper: createWrapper }
      );
      const { result: infiniteResult } = renderHook(
        () => useInfiniteJournals(filters),
        { wrapper: createWrapper }
      );

      await waitFor(() => {
        expect(standardResult.current.isSuccess).toBe(true);
        expect(infiniteResult.current.isSuccess).toBe(true);
      });

      const standardKey = journalKeys.list(filters);
      const infiniteKey = journalKeys.infiniteList(filters, {
        chunkDays: undefined,
        anchorDate: undefined,
      });
      expect(standardKey).not.toEqual(infiniteKey);
    });

    it('should fetch the next chunk when scrolling down (FUTURE)', async () => {
      const firstPage = createMockJournalListResponse(
        [createMockJournal('1')],
        { total: 1, page: 1, total_pages: 1, per_page: 100 }
      );
      const nextPage = createMockJournalListResponse([createMockJournal('2')], {
        total: 1,
        page: 1,
        total_pages: 1,
        per_page: 100,
      });

      mockFetch.mockImplementation(async (...args) => {
        const urlObj = String(args[0]);
        if (urlObj.includes('start_date=2026-04-07'))
          return { ok: true, json: async () => firstPage } as Response;
        if (urlObj.includes('start_date=2026-04-14'))
          return { ok: true, json: async () => nextPage } as Response;
        return {
          ok: true,
          json: async () => createMockJournalListResponse([]),
        } as Response;
      });

      const { result } = renderHook(
        () =>
          useInfiniteJournals({}, { anchorDate: '2026-04-10', chunkDays: 7 }),
        {
          wrapper: createWrapper,
        }
      );

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      // Initial fetch should be: April 7 to April 13
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/journals?start_date=2026-04-07&end_date=2026-04-13&limit=100',
        expect.any(Object)
      );

      await act(async () => {
        await result.current.fetchNextPage();
      });

      // Next fetch (FUTURE) should be: April 14 to April 20
      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          '/api/journals?start_date=2026-04-14&end_date=2026-04-20&limit=100',
          expect.any(Object)
        );
      });
    });

    it('should fetch the previous chunk when scrolling up (PAST)', async () => {
      const firstPage = createMockJournalListResponse(
        [createMockJournal('1')],
        { total: 1, page: 1, total_pages: 1, per_page: 100 }
      );
      const previousPage = createMockJournalListResponse(
        [createMockJournal('2')],
        { total: 1, page: 1, total_pages: 1, per_page: 100 }
      );

      mockFetch.mockImplementation(async (...args) => {
        const urlObj = String(args[0]);
        if (urlObj.includes('start_date=2026-04-07'))
          return { ok: true, json: async () => firstPage } as Response;
        if (urlObj.includes('start_date=2026-03-31'))
          return { ok: true, json: async () => previousPage } as Response;
        return {
          ok: true,
          json: async () => createMockJournalListResponse([]),
        } as Response;
      });

      const { result } = renderHook(
        () =>
          useInfiniteJournals({}, { anchorDate: '2026-04-10', chunkDays: 7 }),
        {
          wrapper: createWrapper,
        }
      );

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      await act(async () => {
        await result.current.fetchPreviousPage();
      });

      // Previous fetch (PAST) should be: March 31 to April 06
      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          '/api/journals?start_date=2026-03-31&end_date=2026-04-06&limit=100',
          expect.any(Object)
        );
      });
    });
  });
});

describe('useDismissReviewItem optimistic updates', () => {
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

  const listKey = reviewItemKeys.list('pending', 1, 20);
  const seedList = () =>
    queryClient.setQueryData(listKey, {
      data: [
        { id: 'r1', type: 'review-items', attributes: {} },
        { id: 'r2', type: 'review-items', attributes: {} },
      ],
    });

  it('removes the dismissed item from cached lists before the request resolves', async () => {
    seedList();

    let resolveFetch: (value: Response) => void = () => {};
    mockFetch.mockReturnValueOnce(
      new Promise<Response>(resolve => {
        resolveFetch = resolve;
      })
    );

    const { result } = renderHook(() => useDismissReviewItem(), {
      wrapper: createWrapper,
    });

    result.current.mutate('r1');

    await waitFor(() => {
      const cached = queryClient.getQueryData(listKey) as {
        data: { id: string }[];
      };
      expect(cached.data.map(i => i.id)).toEqual(['r2']);
    });

    resolveFetch({ ok: true, json: async () => ({}) } as Response);
  });

  it('rolls back the cached list when the dismiss request fails', async () => {
    seedList();

    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ errors: [{ detail: 'Boom' }] }),
    } as Response);

    const { result } = renderHook(() => useDismissReviewItem(), {
      wrapper: createWrapper,
    });

    await expect(result.current.mutateAsync('r1')).rejects.toThrow('Boom');

    const cached = queryClient.getQueryData(listKey) as {
      data: { id: string }[];
    };
    expect(cached.data.map(i => i.id)).toEqual(['r1', 'r2']);
  });
});
