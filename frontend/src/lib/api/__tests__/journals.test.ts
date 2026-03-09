/**
 * @jest-environment jsdom
 */

import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React, { ReactNode } from 'react';
import {
  useJournals,
  useJournal,
  useSearchJournals,
  useJournalTags,
  useCreateJournal,
  useUpdateJournal,
  useDeleteJournal,
  useContactJournals,
  useCalendars,
  useCreateCalendar,
  useUpdateCalendar,
  useDeleteCalendar,
} from '../journals';
import { JournalType } from '@/types/journals';

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
  type: 'journals',
  attributes: createMockJournalAttributes(attributeOverrides),
});

const createMockJournalListResponse = (
  journals: ReturnType<typeof createMockJournal>[]
) => ({
  data: journals,
  meta: { total: journals.length, page: 1, per_page: 20, total_pages: 1 },
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

      // Backend expects singular 'type' and 'tag_id', and 'start_date'/'end_date'
      // Currently only the first type and tag are sent since backend doesn't support multiple
      const expectedUrl =
        '/api/journals?search=test&type=note&contact_id=contact-1&tag_id=tag-1&start_date=2024-01-01&end_date=2024-12-31';
      expect(mockFetch).toHaveBeenCalledWith(expectedUrl, expect.any(Object));
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
            type: 'journal_tag',
            attributes: { name: 'Tag 1', color: '#FF0000', parent_id: null },
          },
          {
            id: '2',
            type: 'journal_tag',
            attributes: { name: 'Tag 2', color: '#00FF00', parent_id: null },
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
});
