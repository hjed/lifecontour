/**
 * @jest-environment jsdom
 */

import { renderHook, waitFor } from '@testing-library/react';
import { createQueryTestHarness } from '@/test-utils';
import { contactKeys, historyKeys, useMergeContact } from '../contacts';

// Mock fetch
globalThis.fetch = jest.fn();

// jest.setup.ts mocks @/lib/constants but omits CONTACTS.BY_ID (used to build the
// merge URL); use the real constants here rather than re-declaring the whole mock.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

// Mock toast
jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

const mockFetch = fetch as jest.MockedFunction<typeof fetch>;
const { toast } = jest.requireMock('sonner') as {
  toast: { success: jest.Mock; error: jest.Mock };
};

const survivorResponse = {
  data: {
    id: '10',
    type: 'contacts',
    attributes: {
      first_name: 'Survivor',
      last_name: 'Person',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    },
  },
};

describe('useMergeContact', () => {
  let harness: ReturnType<typeof createQueryTestHarness>;

  beforeEach(() => {
    harness = createQueryTestHarness();
    jest.clearAllMocks();
  });

  it('POSTs to the survivor merge endpoint with the source id and overrides', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => survivorResponse,
    } as Response);

    const { result } = renderHook(() => useMergeContact(), {
      wrapper: harness.wrapper,
    });

    const response = await result.current.mutateAsync({
      survivorId: '10',
      sourceId: '20',
      overrides: { first_name: 'Custom', is_favourite: false },
    });

    expect(mockFetch).toHaveBeenCalledWith('/api/contacts/10/merge', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        data: {
          type: 'contact-merge',
          attributes: {
            source_contact_id: 20,
            overrides: { first_name: 'Custom', is_favourite: false },
          },
        },
      }),
    });

    expect(response).toEqual(survivorResponse);
  });

  it('omits the overrides key when no overrides are provided', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => survivorResponse,
    } as Response);

    const { result } = renderHook(() => useMergeContact(), {
      wrapper: harness.wrapper,
    });

    await result.current.mutateAsync({ survivorId: '10', sourceId: '20' });

    expect(mockFetch).toHaveBeenCalledWith('/api/contacts/10/merge', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        data: {
          type: 'contact-merge',
          attributes: { source_contact_id: 20 },
        },
      }),
    });
  });

  it('invalidates contacts, both detail caches, and contact history on success', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => survivorResponse,
    } as Response);

    const invalidateSpy = jest.spyOn(harness.queryClient, 'invalidateQueries');

    const { result } = renderHook(() => useMergeContact(), {
      wrapper: harness.wrapper,
    });

    await result.current.mutateAsync({ survivorId: '10', sourceId: '20' });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: contactKeys.all })
      );
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: contactKeys.detail('10') })
      );
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: contactKeys.detail('20') })
      );
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: historyKeys.all })
      );
    });
    expect(toast.success).toHaveBeenCalledWith('Contacts merged successfully');
  });

  it('surfaces the API error detail via an error toast', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({
        errors: [{ detail: 'Cannot merge a contact with itself' }],
      }),
    } as Response);

    const { result } = renderHook(() => useMergeContact(), {
      wrapper: harness.wrapper,
    });

    await expect(
      result.current.mutateAsync({ survivorId: '10', sourceId: '10' })
    ).rejects.toThrow('Cannot merge a contact with itself');

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        'Cannot merge a contact with itself'
      );
    });
  });
});
