/**
 * @jest-environment jsdom
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { createQueryTestHarness, mockApiResponse } from '@/test-utils';
import {
  journalKeys,
  useAddContactRelationship,
  useAddJournalTag,
  useAddJournalType,
  useAdoptChildJournal,
  useJournal,
  useRemoveContactRelationship,
  useRemoveJournalTag,
  useRemoveJournalType,
  useUpdateContactRelationship,
  useUpdateJournal,
  useUpdateJournalField,
  useUpdateTypeData,
  useUpdateTypeDataBatch,
} from '../journals';
import { readEtag, type Versioned } from '../versioned-cache';
import { taskKeys } from '../tasks';
import { JournalType, type JournalResponse } from '@/types/journals';

globalThis.fetch = jest.fn();
const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

const JOURNAL = {
  data: {
    id: '7',
    type: 'journals',
    attributes: {
      title: 'Hike',
      content: '',
      event_date_range: {
        start: '2026-10-01T00:00:00Z',
        end: '2026-10-02T00:00:00Z',
      },
      types: [],
      contacts: [],
      tags: [],
    },
  },
} as unknown as JournalResponse;

function sentIfMatch(call: number): string | undefined {
  const headers = mockFetch.mock.calls[call]?.[1]?.headers as
    Record<string, string> | undefined;
  return headers?.['If-Match'];
}

/** A harness whose cache already holds the journal at version `"e1"`. */
function seeded() {
  const harness = createQueryTestHarness();
  harness.queryClient.setQueryData<Versioned<JournalResponse>>(
    journalKeys.detail('7'),
    { resource: JOURNAL, etag: '"e1"' }
  );
  return harness;
}

describe('journal conditional writes', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it('useJournal keeps the ETag with the cached journal and hands back the journal', async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    mockFetch.mockResolvedValueOnce(mockApiResponse(JOURNAL, { etag: '"e1"' }));

    const { result } = renderHook(() => useJournal('7'), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(JOURNAL);
    expect(readEtag(queryClient, journalKeys.detail('7'))).toBe('"e1"');
  });

  it('useUpdateJournal sends two quick edits one after the other, each guarded by the last', async () => {
    const { queryClient, wrapper } = seeded();
    mockFetch
      .mockResolvedValueOnce(mockApiResponse(JOURNAL, { etag: '"e2"' }))
      .mockResolvedValueOnce(mockApiResponse(JOURNAL, { etag: '"e3"' }));

    const { result } = renderHook(() => useUpdateJournal('7'), { wrapper });
    await act(() =>
      Promise.all([
        result.current.mutateAsync({ title: 'Long hike' }),
        result.current.mutateAsync({ content: 'Muddy' }),
      ])
    );

    expect(mockFetch.mock.calls[0]?.[0]).toBe('/api/journals/7');
    expect(mockFetch.mock.calls[0]?.[1]?.method).toBe('PATCH');
    expect(sentIfMatch(0)).toBe('"e1"');
    expect(sentIfMatch(1)).toBe('"e2"');
    expect(readEtag(queryClient, journalKeys.detail('7'))).toBe('"e3"');
  });

  it('useUpdateJournal refreshes every journal detail when it re-parents', async () => {
    // The old and new parents both list their children, and a Keep mine
    // replay runs only the mutation, so the refresh belongs to it.
    jest.useFakeTimers();
    try {
      const { queryClient, wrapper } = seeded();
      const invalidate = jest.spyOn(queryClient, 'invalidateQueries');
      mockFetch.mockResolvedValueOnce(
        mockApiResponse(JOURNAL, { etag: '"e2"' })
      );

      const { result } = renderHook(() => useUpdateJournal('7'), { wrapper });
      await act(() => result.current.mutateAsync({ parent_id: 3 }));
      await act(async () => {
        jest.advanceTimersByTime(200);
      });

      expect(invalidate).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: journalKeys.details() })
      );
    } finally {
      jest.useRealTimers();
    }
  });

  it('useUpdateJournal keeps the journal its write answers with, not just its tag', async () => {
    // The body is the journal re-read after the commit, and may carry
    // another tab's change; keeping only its tag would pair that version with
    // the older body.
    const { queryClient, wrapper } = seeded();
    const renamed = {
      data: {
        ...JOURNAL.data,
        attributes: { ...JOURNAL.data.attributes, content: 'Elsewhere' },
      },
    } as unknown as JournalResponse;
    mockFetch.mockResolvedValueOnce(mockApiResponse(renamed, { etag: '"e2"' }));

    const { result } = renderHook(() => useUpdateJournal('7'), { wrapper });
    await act(() => result.current.mutateAsync({ title: 'Long hike' }));

    expect(queryClient.getQueryData(journalKeys.detail('7'))).toEqual({
      resource: renamed,
      etag: '"e2"',
    });
  });

  it('useUpdateJournalField guards the field edit', async () => {
    const { queryClient, wrapper } = seeded();
    mockFetch.mockResolvedValueOnce(mockApiResponse(JOURNAL, { etag: '"e2"' }));

    const { result } = renderHook(() => useUpdateJournalField('7'), {
      wrapper,
    });
    await act(() =>
      result.current.mutateAsync({ fieldName: 'title', value: 'Long hike' })
    );

    expect(mockFetch.mock.calls[0]?.[0]).toBe('/api/journals/7/fields/title');
    expect(sentIfMatch(0)).toBe('"e1"');
    expect(readEtag(queryClient, journalKeys.detail('7'))).toBe('"e2"');
  });

  it('useAdoptChildJournal re-parents another journal unconditionally', async () => {
    // The write is to the child, whose version this page has not read.
    const { wrapper } = seeded();
    mockFetch.mockResolvedValueOnce(mockApiResponse(JOURNAL));

    const { result } = renderHook(() => useAdoptChildJournal('7'), {
      wrapper,
    });
    await act(() => result.current.mutateAsync('9'));

    expect(mockFetch.mock.calls[0]?.[0]).toBe('/api/journals/9');
    expect(JSON.parse(String(mockFetch.mock.calls[0]?.[1]?.body))).toEqual({
      data: { type: 'journals', id: '9', attributes: { parent_id: 7 } },
    });
    expect(sentIfMatch(0)).toBeUndefined();
  });

  it('useAdoptChildJournal refreshes the journal lists and the tasks the child carries', async () => {
    // Re-parenting moves the child under a new parent in every list, and a
    // task embeds its journals.
    const { queryClient, wrapper } = seeded();
    const invalidate = jest.spyOn(queryClient, 'invalidateQueries');
    mockFetch.mockResolvedValueOnce(mockApiResponse(JOURNAL));

    const { result } = renderHook(() => useAdoptChildJournal('7'), {
      wrapper,
    });
    await act(() => result.current.mutateAsync('9'));

    const keys = invalidate.mock.calls.map(
      call => (call[0] as { queryKey: readonly unknown[] }).queryKey
    );
    expect(keys).toContainEqual(journalKeys.lists());
    expect(keys).toContainEqual(journalKeys.details());
    expect(keys).toContainEqual(taskKeys.all);
  });

  it('useUpdateTypeDataBatch writes several type blocks as one change, each guarded by the last', async () => {
    // Applying a template writes two blocks; a conflict on either must replay
    // both, so they are one mutation.
    const { queryClient, wrapper } = seeded();
    mockFetch
      .mockResolvedValueOnce(mockApiResponse(JOURNAL, { etag: '"e2"' }))
      .mockResolvedValueOnce(mockApiResponse(JOURNAL, { etag: '"e3"' }));

    const { result } = renderHook(() => useUpdateTypeDataBatch('7'), {
      wrapper,
    });
    await act(() =>
      result.current.mutateAsync({
        updates: [
          {
            journalType: JournalType.ABSEILING_TRIP,
            typeData: { template_id: 't' },
          },
          { journalType: JournalType.CANYONING, typeData: { grade: 'v3a2' } },
        ],
        successMessage: 'Template linked to journal',
      })
    );

    expect(mockFetch.mock.calls.map(call => call[0])).toEqual([
      '/api/journals/7/types/abseiling_trip/data',
      '/api/journals/7/types/canyoning/data',
    ]);
    expect(sentIfMatch(0)).toBe('"e1"');
    expect(sentIfMatch(1)).toBe('"e2"');
    expect(readEtag(queryClient, journalKeys.detail('7'))).toBe('"e3"');
  });

  it('useUpdateTypeDataBatch says which block saved when a later one fails, and re-reads the journal', async () => {
    const { queryClient, wrapper } = seeded();
    const invalidate = jest.spyOn(queryClient, 'invalidateQueries');
    mockFetch
      .mockResolvedValueOnce(mockApiResponse(JOURNAL, { etag: '"e2"' }))
      .mockResolvedValueOnce({
        ok: false,
        status: 422,
        json: async () => ({ errors: [{ detail: 'Grade is invalid' }] }),
      } as Response);

    const { result } = renderHook(() => useUpdateTypeDataBatch('7'), {
      wrapper,
    });
    const failure = await act(() =>
      result.current
        .mutateAsync({
          updates: [
            { journalType: JournalType.ABSEILING_TRIP, typeData: {} },
            { journalType: JournalType.CANYONING, typeData: { grade: 'x' } },
          ],
          successMessage: 'Template linked to journal',
        })
        .catch((error: unknown) => error)
    );

    expect(String(failure)).toContain('abseiling_trip saved');
    expect(String(failure)).toContain('Grade is invalid');
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: journalKeys.detail('7') })
      )
    );
  });

  describe('every journal row write sends the journal tag and stores the next', () => {
    const cases: ReadonlyArray<
      readonly [
        string,
        () => { mutateAsync: (variables: never) => Promise<unknown> },
        unknown,
        string,
        string,
      ]
    > = [
      [
        'adds a type',
        () => useAddJournalType('7'),
        { journalType: JournalType.EVENT },
        'POST',
        '/api/journals/7/types',
      ],
      [
        'removes a type',
        () => useRemoveJournalType('7'),
        { journalType: JournalType.EVENT },
        'DELETE',
        '/api/journals/7/types/event',
      ],
      [
        'updates type data',
        () => useUpdateTypeData('7'),
        { journalType: JournalType.FITNESS, typeData: { distance: 5000 } },
        'PUT',
        '/api/journals/7/types/fitness/data',
      ],
      [
        'adds a contact',
        () => useAddContactRelationship('7'),
        { contactId: '2', relationshipType: 'participant' },
        'POST',
        '/api/journals/7/relationships/contacts',
      ],
      [
        'updates a contact',
        () => useUpdateContactRelationship('7'),
        { contactId: '2', relationshipType: 'participant', status: 'accepted' },
        'PATCH',
        '/api/journals/7/relationships/contacts/2/participant',
      ],
      [
        'removes a contact',
        () => useRemoveContactRelationship('7'),
        { contactId: '2', relationshipType: 'participant' },
        'DELETE',
        '/api/journals/7/relationships/contacts/2/participant',
      ],
      [
        'adds a tag',
        () => useAddJournalTag('7'),
        { tagId: '3' },
        'POST',
        '/api/journals/7/relationships/tags',
      ],
      [
        'removes a tag',
        () => useRemoveJournalTag('7'),
        { tagId: '3' },
        'DELETE',
        '/api/journals/7/relationships/tags/3',
      ],
    ];

    it.each(cases)('%s', async (_name, hook, variables, method, url) => {
      const { queryClient, wrapper } = seeded();
      // The journal as re-read after the write, which may carry another
      // tab's change: it is kept with its tag, not just the tag.
      const reread = {
        data: {
          ...JOURNAL.data,
          attributes: { ...JOURNAL.data.attributes, content: 'Elsewhere' },
        },
      } as unknown as JournalResponse;
      mockFetch.mockResolvedValueOnce(
        mockApiResponse(reread, { etag: '"e2"' })
      );

      const { result } = renderHook(hook, { wrapper });
      await act(() => result.current.mutateAsync(variables as never));

      expect(mockFetch.mock.calls[0]?.[0]).toBe(url);
      expect(mockFetch.mock.calls[0]?.[1]?.method).toBe(method);
      expect(sentIfMatch(0)).toBe('"e1"');
      expect(queryClient.getQueryData(journalKeys.detail('7'))).toEqual({
        resource: reread,
        etag: '"e2"',
      });
    });
  });
});
