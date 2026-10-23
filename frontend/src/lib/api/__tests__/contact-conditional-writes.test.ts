/**
 * @jest-environment jsdom
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { createQueryTestHarness, mockApiResponse } from '@/test-utils';
import {
  contactKeys,
  useContact,
  useUpdateContact,
  useUpdateContactField,
} from '../contacts';
import { readEtag, type Versioned } from '../versioned-cache';
import type { ContactResponse } from '@/types/contacts';

globalThis.fetch = jest.fn();
const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

const CONTACT: ContactResponse = {
  data: {
    id: '1',
    type: 'contacts',
    attributes: {
      first_name: 'Ada',
      last_name: 'Lovelace',
      nick_name: 'Countess',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
      contact_methods: [],
      addresses: [],
      notes: [],
      relationships: [],
    },
  },
};

function sentIfMatch(call: number): string | undefined {
  const headers = mockFetch.mock.calls[call]?.[1]?.headers as
    Record<string, string> | undefined;
  return headers?.['If-Match'];
}

function fieldResponse(field_name: string, new_value: string) {
  return {
    data: {
      type: 'contact_fields',
      id: '1',
      attributes: { field_name, old_value: null, new_value },
    },
  };
}

/** A harness whose cache already holds the contact at version `"e1"`. */
function seeded() {
  const harness = createQueryTestHarness();
  harness.queryClient.setQueryData<Versioned<ContactResponse>>(
    contactKeys.detail('1'),
    { resource: CONTACT, etag: '"e1"' }
  );
  return harness;
}

describe('contact conditional writes', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it('useContact keeps the ETag with the cached contact and hands back the contact', async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    mockFetch.mockResolvedValueOnce(mockApiResponse(CONTACT, { etag: '"e1"' }));

    const { result } = renderHook(() => useContact('1'), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(CONTACT);
    expect(readEtag(queryClient, contactKeys.detail('1'))).toBe('"e1"');
  });

  it('useUpdateContactField guards the edit and keeps the version it committed', async () => {
    const { queryClient, wrapper } = seeded();
    mockFetch.mockResolvedValueOnce(
      mockApiResponse(fieldResponse('nick_name', 'Bob'), { etag: '"e2"' })
    );

    const { result } = renderHook(() => useUpdateContactField('1'), {
      wrapper,
    });
    await act(() =>
      result.current.mutateAsync({ fieldName: 'nick_name', value: 'Bob' })
    );

    expect(sentIfMatch(0)).toBe('"e1"');
    const cached = queryClient.getQueryData<Versioned<ContactResponse>>(
      contactKeys.detail('1')
    );
    expect(cached?.etag).toBe('"e2"');
    expect(cached?.resource.data.attributes.nick_name).toBe('Bob');
  });

  it('useUpdateContactField sends two quick edits one after the other', async () => {
    const { wrapper } = seeded();
    mockFetch
      .mockResolvedValueOnce(
        mockApiResponse(fieldResponse('first_name', 'Augusta'), {
          etag: '"e2"',
        })
      )
      .mockResolvedValueOnce(
        mockApiResponse(fieldResponse('nick_name', 'Bob'), { etag: '"e3"' })
      );

    const { result } = renderHook(() => useUpdateContactField('1'), {
      wrapper,
    });
    await act(() =>
      Promise.all([
        result.current.mutateAsync({
          fieldName: 'first_name',
          value: 'Augusta',
        }),
        result.current.mutateAsync({ fieldName: 'nick_name', value: 'Bob' }),
      ])
    );

    expect(sentIfMatch(0)).toBe('"e1"');
    expect(sentIfMatch(1)).toBe('"e2"');
  });

  it('useUpdateContact stores the contact and the tag the write returned', async () => {
    const { queryClient, wrapper } = seeded();
    const renamed = {
      data: {
        ...CONTACT.data,
        attributes: { ...CONTACT.data.attributes, first_name: 'Augusta' },
      },
    };
    mockFetch.mockResolvedValueOnce(mockApiResponse(renamed, { etag: '"e2"' }));

    const { result } = renderHook(() => useUpdateContact('1'), { wrapper });
    await act(() => result.current.mutateAsync({ first_name: 'Augusta' }));

    expect(sentIfMatch(0)).toBe('"e1"');
    expect(queryClient.getQueryData(contactKeys.detail('1'))).toEqual({
      resource: renamed,
      etag: '"e2"',
    });
  });

  it('writes unconditionally when the contact has not been read', async () => {
    const { wrapper } = createQueryTestHarness();
    mockFetch.mockResolvedValueOnce(
      mockApiResponse(fieldResponse('nick_name', 'Bob'), { etag: '"e2"' })
    );

    const { result } = renderHook(() => useUpdateContactField('1'), {
      wrapper,
    });
    await act(() =>
      result.current.mutateAsync({ fieldName: 'nick_name', value: 'Bob' })
    );

    expect(sentIfMatch(0)).toBeUndefined();
  });
});
