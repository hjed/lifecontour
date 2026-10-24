/**
 * @jest-environment jsdom
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { createQueryTestHarness, mockApiResponse } from '@/test-utils';
import {
  contactKeys,
  useAddContactAddress,
  useAddContactMethod,
  useContact,
  useDeleteContactAddress,
  useDeleteContactMethod,
  useSetContactValueArchived,
  useUpdateContactAddressFields,
  useUpdateContact,
  useUpdateContactField,
  useUpdateContactMethodField,
} from '../contacts';
import { ContactMethodType } from '@/types/contacts';
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

  describe('every contact row write sends the contact tag and stores the next', () => {
    function render<T>(hook: () => T) {
      const harness = seeded();
      const { result } = renderHook(hook, { wrapper: harness.wrapper });
      return { harness, result };
    }

    async function expectGuarded(
      harness: ReturnType<typeof seeded>,
      run: () => Promise<unknown>,
      method: string,
      url: string,
      status: 200 | 201 | 204
    ) {
      mockFetch.mockResolvedValueOnce(
        mockApiResponse(status === 204 ? undefined : CONTACT, {
          status,
          etag: '"e2"',
        })
      );

      await act(run);

      expect(mockFetch.mock.calls[0]?.[0]).toBe(url);
      expect(mockFetch.mock.calls[0]?.[1]?.method).toBe(method);
      expect(sentIfMatch(0)).toBe('"e1"');
      expect(readEtag(harness.queryClient, contactKeys.detail('1'))).toBe(
        '"e2"'
      );
    }

    it('adds a contact method', async () => {
      const { harness, result } = render(() => useAddContactMethod('1'));
      await expectGuarded(
        harness,
        () =>
          result.current.mutateAsync({
            method: {
              method_type: ContactMethodType.EMAIL,
              value: 'a@b.c',
              is_primary: false,
            },
          }),
        'POST',
        '/api/contacts/1/methods',
        201
      );
    });

    it('edits a contact method field', async () => {
      const { harness, result } = render(() =>
        useUpdateContactMethodField('1')
      );
      await expectGuarded(
        harness,
        () =>
          result.current.mutateAsync({
            methodId: 'm1',
            fieldName: 'value',
            value: 'x@y.z',
          }),
        'PATCH',
        '/api/contacts/1/methods/m1/fields/value',
        200
      );
    });

    it('deletes a contact method (204)', async () => {
      const { harness, result } = render(() => useDeleteContactMethod('1'));
      await expectGuarded(
        harness,
        () => result.current.mutateAsync({ methodId: 'm1' }),
        'DELETE',
        '/api/contacts/1/methods/m1',
        204
      );
    });

    it('adds an address', async () => {
      const { harness, result } = render(() => useAddContactAddress('1'));
      await expectGuarded(
        harness,
        () =>
          result.current.mutateAsync({
            address: {
              street_line_1: '1 George St',
              country_code: 'AU',
              is_primary: false,
            },
          }),
        'POST',
        '/api/contacts/1/addresses',
        201
      );
    });

    it('edits an address field', async () => {
      const { harness, result } = render(() =>
        useUpdateContactAddressFields('1')
      );
      await expectGuarded(
        harness,
        () =>
          result.current.mutateAsync({
            addressId: 'a1',
            fields: { locality: 'Hobart' },
          }),
        'PATCH',
        '/api/contacts/1/addresses/a1/fields/locality',
        200
      );
    });

    it('saves several address fields as one write, each guarded by the last', async () => {
      const { harness, result } = render(() =>
        useUpdateContactAddressFields('1')
      );
      mockFetch
        .mockResolvedValueOnce(mockApiResponse({}, { etag: '"e2"' }))
        .mockResolvedValueOnce(mockApiResponse({}, { etag: '"e3"' }));

      await act(() =>
        result.current.mutateAsync({
          addressId: 'a1',
          fields: { locality: 'Hobart', postal_code: '7000' },
        })
      );

      expect(mockFetch.mock.calls.map(call => call[0])).toEqual([
        '/api/contacts/1/addresses/a1/fields/locality',
        '/api/contacts/1/addresses/a1/fields/postal_code',
      ]);
      expect(sentIfMatch(0)).toBe('"e1"');
      expect(sentIfMatch(1)).toBe('"e2"');
      expect(readEtag(harness.queryClient, contactKeys.detail('1'))).toBe(
        '"e3"'
      );
    });

    it('deletes an address (204)', async () => {
      const { harness, result } = render(() => useDeleteContactAddress('1'));
      await expectGuarded(
        harness,
        () => result.current.mutateAsync({ addressId: 'a1' }),
        'DELETE',
        '/api/contacts/1/addresses/a1',
        204
      );
    });

    it('archives a method', async () => {
      const { harness, result } = render(() => useSetContactValueArchived('1'));
      await expectGuarded(
        harness,
        () =>
          result.current.mutateAsync({
            kind: 'method',
            id: 'm1',
            archived: true,
          }),
        'PATCH',
        '/api/contacts/1/methods/m1/fields/is_archived',
        200
      );
    });

    it('keeps the contact an add answers with, not just its tag', async () => {
      const { harness, result } = render(() => useAddContactMethod('1'));
      const withMethod = {
        data: {
          ...CONTACT.data,
          attributes: { ...CONTACT.data.attributes, nick_name: 'Elsewhere' },
        },
      };
      mockFetch.mockResolvedValueOnce(
        mockApiResponse(withMethod, { status: 201, etag: '"e2"' })
      );

      await act(() =>
        result.current.mutateAsync({
          method: {
            method_type: ContactMethodType.EMAIL,
            value: 'a@b.c',
            is_primary: false,
          },
        })
      );

      expect(harness.queryClient.getQueryData(contactKeys.detail('1'))).toEqual(
        { resource: withMethod, etag: '"e2"' }
      );
    });
  });
});
