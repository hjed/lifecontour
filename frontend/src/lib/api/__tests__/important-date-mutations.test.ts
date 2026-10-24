/**
 * @jest-environment jsdom
 */

import { renderHook, waitFor } from '@testing-library/react';
import { createQueryTestHarness, mockApiResponse } from '@/test-utils';
import {
  contactKeys,
  historyKeys,
  useAddContactImportantDate,
  useDeleteContactImportantDate,
  useUpdateContactImportantDate,
} from '../contacts';
import type { Versioned } from '../versioned-cache';
import {
  ImportantDatePrecision,
  ImportantDateTypeEnum,
} from '@/types/contacts';

// Mock fetch
globalThis.fetch = jest.fn();

// jest.setup.ts mocks @/lib/constants but omits CONTACTS.BASE (used to build the
// important-date URLs); use the real constants here rather than re-declaring the
// whole mock.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

/** The contact as the server reports it after the edit landed. */
const editedContactResponse = {
  data: {
    id: '10',
    type: 'contacts',
    attributes: {
      first_name: 'Ada',
      last_name: 'Lovelace',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-02T00:00:00Z',
      important_dates: [
        {
          id: '1',
          type: 'important_dates',
          attributes: {
            date_type: ImportantDateTypeEnum.BIRTHDAY,
            precision: ImportantDatePrecision.FULL,
            year: 1991,
            month: 5,
            day: 15,
          },
        },
      ],
    },
  },
};

/** The same contact as the cache held it before the edit. */
const staleContactResponse = {
  ...editedContactResponse,
  data: {
    ...editedContactResponse.data,
    attributes: {
      ...editedContactResponse.data.attributes,
      updated_at: '2024-01-01T00:00:00Z',
      important_dates: [
        {
          id: '1',
          type: 'important_dates',
          attributes: {
            date_type: ImportantDateTypeEnum.BIRTHDAY,
            precision: ImportantDatePrecision.FULL,
            year: 1990,
            month: 5,
            day: 15,
          },
        },
      ],
    },
  },
};

const birthday = {
  date_type: ImportantDateTypeEnum.BIRTHDAY,
  precision: ImportantDatePrecision.FULL,
  year: 1991,
  month: 5,
  day: 15,
};

describe('important date mutations', () => {
  let harness: ReturnType<typeof createQueryTestHarness>;

  beforeEach(() => {
    harness = createQueryTestHarness();
    jest.clearAllMocks();
  });

  describe('useUpdateContactImportantDate', () => {
    it('PUTs the whole date to its own endpoint', async () => {
      mockFetch.mockResolvedValueOnce(
        mockApiResponse(editedContactResponse, { etag: '"e2"' })
      );

      const { result } = renderHook(() => useUpdateContactImportantDate('10'), {
        wrapper: harness.wrapper,
      });

      await result.current.mutateAsync({
        dateId: '1',
        date: birthday,
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/contacts/10/important-dates/1',
        expect.objectContaining({
          method: 'PUT',
          credentials: 'include',
          body: JSON.stringify({
            data: {
              type: 'contact_important_dates',
              id: '1',
              attributes: birthday,
            },
          }),
        })
      );
    });

    it('makes the detail cache current before the mutation settles', async () => {
      // The editor closes when mutateAsync resolves and seeds its inputs from
      // whatever the cache holds when it reopens. If the cache were still stale
      // at that moment, a second edit would submit - and so restore - the old
      // values, undoing the save that just succeeded.
      harness.queryClient.setQueryData(contactKeys.detail('10'), {
        resource: staleContactResponse,
        etag: '"e1"',
      });
      mockFetch.mockResolvedValueOnce(
        mockApiResponse(editedContactResponse, { etag: '"e2"' })
      );

      const { result } = renderHook(() => useUpdateContactImportantDate('10'), {
        wrapper: harness.wrapper,
      });

      await result.current.mutateAsync({
        dateId: '1',
        date: birthday,
      });

      const versioned = harness.queryClient.getQueryData<
        Versioned<typeof editedContactResponse>
      >(contactKeys.detail('10'));
      // The tag of the same read is kept, so later guarded edits stay guarded.
      expect(versioned?.etag).toBe('"e2"');
      const cached = versioned?.resource;
      expect(cached?.data.attributes.important_dates[0].attributes.year).toBe(
        1991
      );
    });

    it('refreshes the activity feed, which the edit writes history rows to', async () => {
      mockFetch.mockResolvedValueOnce(
        mockApiResponse(editedContactResponse, { etag: '"e2"' })
      );

      const invalidateSpy = jest.spyOn(
        harness.queryClient,
        'invalidateQueries'
      );

      const { result } = renderHook(() => useUpdateContactImportantDate('10'), {
        wrapper: harness.wrapper,
      });

      await result.current.mutateAsync({
        dateId: '1',
        date: birthday,
      });

      await waitFor(() => {
        expect(invalidateSpy).toHaveBeenCalledWith(
          expect.objectContaining({ queryKey: contactKeys.lists() })
        );
        expect(invalidateSpy).toHaveBeenCalledWith(
          expect.objectContaining({ queryKey: historyKeys.all })
        );
      });
    });

    it('rejects with the API error detail so the editor can stay open', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({
          errors: [{ detail: 'Contact already has a birthday date defined' }],
        }),
      } as Response);

      const { result } = renderHook(() => useUpdateContactImportantDate('10'), {
        wrapper: harness.wrapper,
      });

      await expect(
        result.current.mutateAsync({
          dateId: '1',
          date: birthday,
        })
      ).rejects.toThrow('Contact already has a birthday date defined');
    });
  });

  describe('useAddContactImportantDate', () => {
    it('POSTs to the collection and makes the detail cache current', async () => {
      harness.queryClient.setQueryData(contactKeys.detail('10'), {
        resource: staleContactResponse,
        etag: '"e1"',
      });
      mockFetch.mockResolvedValueOnce(
        mockApiResponse(editedContactResponse, { etag: '"e2"' })
      );

      const { result } = renderHook(() => useAddContactImportantDate('10'), {
        wrapper: harness.wrapper,
      });

      await result.current.mutateAsync({ date: birthday });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/contacts/10/important-dates',
        expect.objectContaining({ method: 'POST' })
      );
      const versioned = harness.queryClient.getQueryData<
        Versioned<typeof editedContactResponse>
      >(contactKeys.detail('10'));
      // The tag of the same read is kept, so later guarded edits stay guarded.
      expect(versioned?.etag).toBe('"e2"');
      const cached = versioned?.resource;
      expect(cached?.data.attributes.important_dates[0].attributes.year).toBe(
        1991
      );
    });
  });

  describe('useDeleteContactImportantDate', () => {
    it('DELETEs the date and refreshes details, lists and history', async () => {
      mockFetch.mockResolvedValueOnce(
        mockApiResponse(undefined, { status: 204 })
      );

      const invalidateSpy = jest.spyOn(
        harness.queryClient,
        'invalidateQueries'
      );

      const { result } = renderHook(() => useDeleteContactImportantDate('10'), {
        wrapper: harness.wrapper,
      });

      await result.current.mutateAsync({ dateId: '1' });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/contacts/10/important-dates/1',
        expect.objectContaining({ method: 'DELETE', credentials: 'include' })
      );

      // A delete answers 204, so there is no payload to seed the cache with -
      // the detail query has to be invalidated instead.
      await waitFor(() => {
        expect(invalidateSpy).toHaveBeenCalledWith(
          expect.objectContaining({ queryKey: contactKeys.detail('10') })
        );
        expect(invalidateSpy).toHaveBeenCalledWith(
          expect.objectContaining({ queryKey: historyKeys.all })
        );
      });
    });
  });
});
