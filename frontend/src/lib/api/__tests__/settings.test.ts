/**
 * @jest-environment jsdom
 */

import { fetchUserSettings, updateTimezone } from '../settings';

globalThis.fetch = jest.fn();
const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

describe('settings API', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  describe('fetchUserSettings', () => {
    it('GETs the user settings endpoint with credentials', async () => {
      const mockResponse = {
        data: {
          id: 'user-1',
          type: 'user_settings',
          attributes: { timezone: 'Australia/Sydney' },
        },
      };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const result = await fetchUserSettings();

      expect(mockFetch).toHaveBeenCalledWith('/api/user-settings', {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      });
      expect(result).toEqual(mockResponse);
    });

    it('throws the API error detail on failure', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({
          errors: [{ detail: 'boom' }],
        }),
      } as Response);

      await expect(fetchUserSettings()).rejects.toThrow('boom');
    });
  });

  describe('updateTimezone', () => {
    it('PUTs the timezone in the request body', async () => {
      const mockResponse = {
        data: {
          id: 'user-1',
          type: 'user_settings',
          attributes: { timezone: 'America/New_York' },
        },
      };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const result = await updateTimezone('America/New_York');

      expect(mockFetch).toHaveBeenCalledWith('/api/user-settings', {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timezone: 'America/New_York' }),
      });
      expect(result).toEqual(mockResponse);
    });
  });
});
