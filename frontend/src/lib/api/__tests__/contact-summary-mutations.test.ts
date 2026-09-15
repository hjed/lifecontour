/**
 * Tests for the contact summary configuration API client.
 */

import { updateContactSummary } from '../contacts';

global.fetch = jest.fn();
const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

describe('Contact API - Summary configuration', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  describe('updateContactSummary', () => {
    it('sends a JSON:API PATCH to the contact summary endpoint', async () => {
      const mockResponse = {
        data: {
          type: 'contacts' as const,
          id: '42',
          attributes: { first_name: 'Ada' },
        },
      };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const result = await updateContactSummary('42', { is_disabled: true });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/contacts/42/summary',
        expect.objectContaining({
          method: 'PATCH',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ data: { is_disabled: true } }),
        })
      );
      expect(result).toEqual(mockResponse);
    });

    it('throws the API error detail when the update fails', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => ({
          errors: [{ detail: 'Contact not found' }],
        }),
      } as Response);

      await expect(
        updateContactSummary('999', { is_disabled: false })
      ).rejects.toThrow('Contact not found');
    });
  });
});
