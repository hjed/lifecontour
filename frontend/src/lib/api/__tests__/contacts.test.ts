/**
 * @jest-environment jsdom
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React, { ReactNode } from 'react';
import {
  contactKeys,
  useInfiniteContacts,
  useInfiniteSearchContacts,
  useContacts,
  useContact,
  useSearchContacts,
  useTags,
  useCreateContact,
  useUpdateContact,
  useDeleteContact,
} from '../contacts';
import { ContactFormData } from '@/types/contacts';

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

function createInfiniteContactsResponse(
  meta: {
    total_count?: number;
    current_page?: number;
    page_count?: number;
    per_page?: number;
  } = {}
) {
  return {
    data: [],
    meta: {
      total_count: 1,
      current_page: 1,
      page_count: 1,
      per_page: 20,
      ...meta,
    },
  };
}

describe('Contacts API', () => {
  let queryClient: QueryClient;

  const createWrapper = ({ children }: { children: ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);

  async function expectDistinctQueryStates<
    TStandardResult extends { isSuccess: boolean },
    TInfiniteResult extends { isSuccess: boolean },
  >({
    standardHook,
    infiniteHook,
    standardKey,
    infiniteKey,
  }: {
    standardHook: () => TStandardResult;
    infiniteHook: () => TInfiniteResult;
    standardKey: readonly unknown[];
    infiniteKey: readonly unknown[];
  }) {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => createInfiniteContactsResponse(),
    } as Response);

    const { result: standardResult } = renderHook(standardHook, {
      wrapper: createWrapper,
    });
    const { result: infiniteResult } = renderHook(infiniteHook, {
      wrapper: createWrapper,
    });

    await waitFor(() => {
      expect(standardResult.current.isSuccess).toBe(true);
      expect(infiniteResult.current.isSuccess).toBe(true);
    });

    expect(standardKey).not.toEqual(infiniteKey);
    expect(queryClient.getQueryState(standardKey)).toBeDefined();
    expect(queryClient.getQueryState(infiniteKey)).toBeDefined();
  }

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

  describe('useContacts', () => {
    it('should fetch contacts successfully', async () => {
      const mockResponse = {
        data: [
          {
            id: '1',
            type: 'contacts',
            attributes: {
              first_name: 'John',
              last_name: 'Doe',
              middle_name: '',
              nick_name: '',
              created_at: '2024-01-01T00:00:00Z',
              updated_at: '2024-01-01T00:00:00Z',
              contact_methods: [],
              addresses: [],
              notes: [],
            },
            relationships: {
              tags: { data: [] },
            },
          },
        ],
        meta: { total: 1, page: 1, per_page: 20, total_pages: 1 },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(() => useContacts(), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(result.current.data).toEqual(mockResponse);
      expect(mockFetch).toHaveBeenCalledWith('/api/contacts?', {
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
      });
    });

    it('should handle fetch error', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({
          errors: [{ detail: 'Server error' }],
        }),
      } as Response);

      const { result } = renderHook(() => useContacts(), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isError).toBe(true);
      });

      expect(result.current.error?.message).toBe('Server error');
    });

    it('should apply filters to query', async () => {
      const filters = {
        search: 'john',
        tags: ['1', '2'], // Use tag IDs as strings (will be parsed to integers)
        created_after: '2024-01-01',
        created_before: '2024-12-31',
        page: 2,
        limit: 25,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ data: [], meta: {} }),
      } as Response);

      renderHook(() => useContacts(filters), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      const expectedUrl =
        '/api/contacts?search=john&tag_ids=1&tag_ids=2&created_after=2024-01-01&created_before=2024-12-31&page=2&limit=25';
      expect(mockFetch).toHaveBeenCalledWith(expectedUrl, expect.any(Object));
    });
  });

  describe('useInfiniteContacts', () => {
    it('should use a distinct query key from useContacts for the same filters', async () => {
      const filters = {};

      const useContactsHook = () => useContacts(filters);
      const useInfiniteContactsHook = () => useInfiniteContacts(filters);

      await expectDistinctQueryStates({
        standardHook: useContactsHook,
        infiniteHook: useInfiniteContactsHook,
        standardKey: contactKeys.list(filters),
        infiniteKey: contactKeys.infiniteList(filters),
      });
    });

    it('should fetch the next contact page when available', async () => {
      const firstPage = createInfiniteContactsResponse({
        total_count: 2,
        current_page: 1,
        page_count: 2,
        per_page: 1,
      });
      const secondPage = createInfiniteContactsResponse({
        total_count: 2,
        current_page: 2,
        page_count: 2,
        per_page: 1,
      });

      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          json: async () => firstPage,
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: async () => secondPage,
        } as Response);

      const { result } = renderHook(() => useInfiniteContacts(), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      await waitFor(() => {
        expect(result.current.hasNextPage).toBe(true);
      });

      await act(async () => {
        await result.current.fetchNextPage();
      });

      await waitFor(() => {
        expect(result.current.data?.pages).toHaveLength(2);
      });

      expect(mockFetch).toHaveBeenNthCalledWith(2, '/api/contacts?page=2', {
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
      });
    });
  });

  describe('useContact', () => {
    it('should fetch single contact successfully', async () => {
      const mockResponse = {
        data: {
          id: '1',
          type: 'contacts',
          attributes: {
            first_name: 'John',
            last_name: 'Doe',
            middle_name: '',
            nick_name: '',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            contact_methods: [],
            addresses: [],
            notes: [],
          },
          relationships: {
            tags: { data: [] },
          },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(() => useContact('1'), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(result.current.data).toEqual(mockResponse);
      expect(mockFetch).toHaveBeenCalledWith('/api/contacts/1', {
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
      });
    });
  });

  describe('useSearchContacts', () => {
    it('should search contacts successfully', async () => {
      const mockResponse = {
        data: [],
        meta: { total: 0, page: 1, per_page: 20, total_pages: 0 },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(() => useSearchContacts('john'), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(result.current.data).toEqual(mockResponse);
      expect(mockFetch).toHaveBeenCalledWith('/api/search/contacts?q=john', {
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
      });
    });

    it('should not search with empty query', () => {
      const { result } = renderHook(() => useSearchContacts(''), {
        wrapper: createWrapper,
      });

      expect(result.current.fetchStatus).toBe('idle');
      expect(mockFetch).not.toHaveBeenCalled();
    });
  });

  describe('useInfiniteSearchContacts', () => {
    it('should use a distinct query key from useSearchContacts', async () => {
      const query = 'john';

      const useSearchContactsHook = () => useSearchContacts(query);
      const useInfiniteSearchContactsHook = () =>
        useInfiniteSearchContacts(query);

      await expectDistinctQueryStates({
        standardHook: useSearchContactsHook,
        infiniteHook: useInfiniteSearchContactsHook,
        standardKey: contactKeys.search(`${query}-{}`),
        infiniteKey: contactKeys.infiniteSearch(`${query}-{}`),
      });
    });

    it('should fetch the next search page when available', async () => {
      const firstPage = createInfiniteContactsResponse({
        total_count: 2,
        current_page: 1,
        page_count: 2,
        per_page: 1,
      });
      const secondPage = createInfiniteContactsResponse({
        total_count: 2,
        current_page: 2,
        page_count: 2,
        per_page: 1,
      });

      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          json: async () => firstPage,
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: async () => secondPage,
        } as Response);

      const { result } = renderHook(() => useInfiniteSearchContacts('john'), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      await waitFor(() => {
        expect(result.current.hasNextPage).toBe(true);
      });

      await act(async () => {
        await result.current.fetchNextPage();
      });

      await waitFor(() => {
        expect(result.current.data?.pages).toHaveLength(2);
      });

      expect(mockFetch).toHaveBeenNthCalledWith(
        2,
        '/api/search/contacts?q=john&page=2',
        {
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
          },
        }
      );
    });
  });

  describe('useCreateContact', () => {
    it('should create contact successfully', async () => {
      const mockResponse = {
        data: {
          id: '1',
          type: 'contacts',
          attributes: {
            first_name: 'John',
            last_name: 'Doe',
            middle_name: '',
            nick_name: '',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            contact_methods: [],
            addresses: [],
            notes: [],
          },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(() => useCreateContact(), {
        wrapper: createWrapper,
      });

      const contactData: ContactFormData = {
        first_name: 'John',
        last_name: 'Doe',
        middle_name: '',
        nick_name: '',
        contact_methods: [],
        addresses: [],
        notes: [],
      };

      await result.current.mutateAsync(contactData);

      expect(mockFetch).toHaveBeenCalledWith('/api/contacts', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          data: {
            type: 'contacts',
            attributes: contactData,
          },
        }),
      });
    });
  });

  describe('useUpdateContact', () => {
    it('should update contact successfully', async () => {
      const mockResponse = {
        data: {
          id: '1',
          type: 'contacts',
          attributes: {
            first_name: 'Jane',
            last_name: 'Doe',
            middle_name: '',
            nick_name: '',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            contact_methods: [],
            addresses: [],
            notes: [],
          },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(() => useUpdateContact(), {
        wrapper: createWrapper,
      });

      const contactData: ContactFormData = {
        first_name: 'Jane',
        last_name: 'Doe',
        middle_name: '',
        nick_name: '',
        contact_methods: [],
        addresses: [],
        notes: [],
      };

      await result.current.mutateAsync({ id: '1', data: contactData });

      expect(mockFetch).toHaveBeenCalledWith('/api/contacts/1', {
        method: 'PUT',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          data: {
            type: 'contacts',
            id: '1',
            attributes: contactData,
          },
        }),
      });
    });
  });

  describe('useDeleteContact', () => {
    it('should delete contact successfully', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
      } as Response);

      const { result } = renderHook(() => useDeleteContact(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync('1');

      expect(mockFetch).toHaveBeenCalledWith('/api/contacts/1', {
        method: 'DELETE',
        credentials: 'include',
      });
    });
  });

  describe('useTags', () => {
    it('should fetch tags successfully', async () => {
      const mockResponse = {
        data: [
          {
            id: '1',
            type: 'tags',
            attributes: {
              name: 'work',
              color: '#blue',
            },
          },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const { result } = renderHook(() => useTags(), {
        wrapper: createWrapper,
      });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(result.current.data).toEqual(mockResponse);
      expect(mockFetch).toHaveBeenCalledWith('/api/tags', {
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
      });
    });
  });
});
