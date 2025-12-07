/**
 * @jest-environment jsdom
 */

import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React, { ReactNode } from 'react';
import {
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

describe('Contacts API', () => {
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
        status: 500,
        statusText: 'Internal Server Error',
        headers: new Headers({ 'content-type': 'application/json' }),
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
        '/api/contacts?search=john&tag_ids=1&tag_ids=2&created_after=2024-01-01&created_before=2024-12-31';
      expect(mockFetch).toHaveBeenCalledWith(expectedUrl, expect.any(Object));
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
