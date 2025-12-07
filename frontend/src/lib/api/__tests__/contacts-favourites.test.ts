/**
 * Tests for contact API client favourites functionality.
 */

import { fetchContacts, toggleContactFavourite } from '../contacts';
import { ContactFilters } from '@/types/contacts';

// Mock fetch globally
globalThis.fetch = jest.fn();
const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

describe('Contact API - Favourites', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  describe('fetchContacts with favourite filter', () => {
    it('should include favourite=true in query params', async () => {
      const mockResponse = {
        data: [],
        meta: { total: 0, page: 1, limit: 20 },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const filters: ContactFilters = {
        favourite: true,
      };

      await fetchContacts(filters);

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/contacts?favourite=true',
        expect.objectContaining({
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
          },
        })
      );
    });

    it('should include favourite=false in query params', async () => {
      const mockResponse = {
        data: [],
        meta: { total: 0, page: 1, limit: 20 },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const filters: ContactFilters = {
        favourite: false,
      };

      await fetchContacts(filters);

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/contacts?favourite=false',
        expect.objectContaining({
          credentials: 'include',
        })
      );
    });

    it('should not include favourite param when undefined', async () => {
      const mockResponse = {
        data: [],
        meta: { total: 0, page: 1, limit: 20 },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const filters: ContactFilters = {
        search: 'john',
      };

      await fetchContacts(filters);

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/contacts?search=john',
        expect.objectContaining({
          credentials: 'include',
        })
      );
    });
  });

  describe('toggleContactFavourite', () => {
    it('should make POST request to favourite endpoint', async () => {
      const mockContact = {
        type: 'contacts' as const,
        id: '1',
        attributes: {
          first_name: 'John',
          last_name: 'Doe',
          is_favourite: true,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
          contact_methods: [],
          addresses: [],
          notes: [],
        },
      };

      const mockResponse = {
        data: mockContact,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const result = await toggleContactFavourite('1');

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/contacts/1/favourite',
        expect.objectContaining({
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
          },
        })
      );

      expect(result.data.attributes.is_favourite).toBe(true);
    });

    it('should handle API errors', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => ({
          errors: [{ detail: 'Contact not found' }],
        }),
      } as Response);

      await expect(toggleContactFavourite('999')).rejects.toThrow();
    });
  });
});
