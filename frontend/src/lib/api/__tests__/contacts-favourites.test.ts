/**
 * Tests for contact API client favourites functionality.
 */

import { fetchContacts } from '../contacts';
import { ContactFilters } from '@/types/contacts';

// Mock fetch globally
global.fetch = jest.fn();
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
});
