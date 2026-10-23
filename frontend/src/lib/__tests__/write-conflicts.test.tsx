/**
 * @jest-environment jsdom
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import {
  onlineManager,
  QueryClient,
  QueryClientProvider,
  type Mutation,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { aggregateWrite, sendGuarded } from '@/lib/api/aggregate-write';
import {
  ApiError,
  PreconditionFailedError,
} from '@/lib/api/conditional-request';
import {
  readEtag,
  unwrapResource,
  type Versioned,
} from '@/lib/api/versioned-cache';
import { createAppQueryClient } from '@/lib/query-client';
import {
  dismissWriteConflict,
  getWriteConflicts,
  handleWriteConflict,
  resetWriteConflicts,
} from '@/lib/write-conflicts';

const KEY = ['contacts', 'detail', '1'] as const;
const REF = { kind: 'contact', id: '1', detailKey: KEY } as const;

interface Doc {
  data: { attributes: { first_name: string; nick_name: string } };
}

function doc(first_name: string, nick_name: string): Doc {
  return { data: { attributes: { first_name, nick_name } } };
}

/** The server: the contact as it now stands, and what each write does. */
const server = {
  current: { resource: doc('Ada', 'Countess'), etag: '"e1"' } as Versioned<Doc>,
};
const read = jest.fn(async () => server.current);
/** A separate read nested under the detail key, as a contact's tags are. */
const readTags = jest.fn(async (): Promise<{ data: string[] }> => ({
  data: [],
}));
const write = jest.fn<
  Promise<{ body: undefined; etag: string }>,
  [string | null, string]
>();

function useContactDetail() {
  // No query retries, so a failed re-read fails at once.
  return useQuery({
    queryKey: KEY,
    queryFn: read,
    select: unwrapResource,
    retry: false,
  });
}

function useEditNickname() {
  const queryClient = useQueryClient();
  return useMutation({
    ...aggregateWrite(REF, (nickname: string) => `Nickname → ${nickname}`),
    mutationFn: (nickname: string) =>
      sendGuarded(queryClient, KEY, ifMatch => write(ifMatch, nickname)),
  });
}

function useContactTags() {
  return useQuery({
    queryKey: [...KEY, 'tags'],
    queryFn: readTags,
    retry: false,
  });
}

function useContactPage() {
  return {
    detail: useContactDetail(),
    tags: useContactTags(),
    edit: useEditNickname(),
  };
}

/** Renders the contact's detail and an inline edit, as the page does. */
async function setup() {
  const queryClient = createAppQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const { result, unmount } = renderHook(useContactPage, { wrapper });
  await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));
  /** Edits the nickname, swallowing the refusal the dialog reports. */
  const edit = (nickname: string) =>
    act(async () => {
      await result.current.edit.mutateAsync(nickname).catch(() => undefined);
    });
  /** Leaves the page and lets the cache evict the record, as gcTime would. */
  const leaveAndEvict = () => {
    unmount();
    queryClient.removeQueries({ queryKey: KEY });
  };
  /** Opens the page again on the same cache. */
  const revisit = () => renderHook(useContactPage, { wrapper });
  return { queryClient, result, edit, leaveAndEvict, revisit };
}

function refuse(): never {
  throw new PreconditionFailedError('moved on', 'PRECONDITION_FAILED', {
    current_etag: '"e9"',
  });
}

describe('write conflicts', () => {
  beforeEach(() => {
    resetWriteConflicts();
    read.mockClear();
    write.mockReset();
    server.current = { resource: doc('Ada', 'Countess'), etag: '"e1"' };
  });

  it('runs two quick writes in order, each guarded by the tag the previous one returned', async () => {
    const { queryClient, result } = await setup();
    write
      .mockResolvedValueOnce({ body: undefined, etag: '"e2"' })
      .mockResolvedValueOnce({ body: undefined, etag: '"e3"' });

    await act(async () => {
      await Promise.all([
        result.current.edit.mutateAsync('Bob'),
        result.current.edit.mutateAsync('Rob'),
      ]);
    });

    expect(write.mock.calls).toEqual([
      ['"e1"', 'Bob'],
      ['"e2"', 'Rob'],
    ]);
    expect(readEtag(queryClient, KEY)).toBe('"e3"');
    expect(getWriteConflicts()).toEqual([]);
  });

  it('re-reads the aggregate on a 412 and reports what changed, without retrying', async () => {
    const { queryClient, result, edit } = await setup();
    write.mockImplementationOnce(async () => refuse());
    server.current = { resource: doc('Augusta', 'Countess'), etag: '"e9"' };

    await edit('Bob');

    await waitFor(() => expect(getWriteConflicts()).toHaveLength(1));
    expect(write).toHaveBeenCalledTimes(1);
    expect(getWriteConflicts()[0]).toMatchObject({
      kind: 'contact',
      refreshed: true,
      changed: ['First name'],
      attempted: 'Nickname → Bob',
    });
    expect(readEtag(queryClient, KEY)).toBe('"e9"');
    expect(result.current.detail.data).toEqual(doc('Augusta', 'Countess'));
  });

  it('re-reads the reads nested under the aggregate too, before reporting', async () => {
    // The dialog says the page now shows the latest version; that has to hold
    // for everything the page reads about the record, its tags included.
    const { edit } = await setup();
    write.mockImplementationOnce(async () => refuse());
    readTags.mockClear();

    await edit('Bob');
    await waitFor(() => expect(getWriteConflicts()).toHaveLength(1));

    expect(readTags).toHaveBeenCalledTimes(1);
  });

  it('says when the re-read failed, and can try it again', async () => {
    const { queryClient, edit } = await setup();
    write.mockImplementationOnce(async () => refuse());
    read.mockRejectedValueOnce(new Error('offline'));

    await edit('Bob');
    await waitFor(() => expect(getWriteConflicts()).toHaveLength(1));
    expect(getWriteConflicts()[0]).toMatchObject({
      refreshed: false,
      changed: [],
    });
    expect(readEtag(queryClient, KEY)).toBe('"e1"');

    server.current = { resource: doc('Augusta', 'Countess'), etag: '"e9"' };
    await act(async () => {
      await getWriteConflicts()[0]?.retryRefresh();
    });

    expect(getWriteConflicts()[0]).toMatchObject({
      refreshed: true,
      changed: ['First name'],
    });
    expect(readEtag(queryClient, KEY)).toBe('"e9"');
  });

  it('keeps mine by re-applying the write with the refreshed tag', async () => {
    const { edit } = await setup();
    write.mockImplementationOnce(async () => refuse());
    server.current = { resource: doc('Augusta', 'Countess'), etag: '"e9"' };
    await edit('Bob');
    await waitFor(() => expect(getWriteConflicts()).toHaveLength(1));
    write.mockResolvedValueOnce({ body: undefined, etag: '"e10"' });

    const [conflict] = getWriteConflicts();
    await act(async () => {
      await conflict?.reapply();
    });

    expect(write).toHaveBeenLastCalledWith('"e9"', 'Bob');
    expect(getWriteConflicts()).toEqual([]);
  });

  it('keeps the conflict open when re-applying fails for another reason', async () => {
    const { edit } = await setup();
    write.mockImplementationOnce(async () => refuse());
    await edit('Bob');
    await waitFor(() => expect(getWriteConflicts()).toHaveLength(1));
    write.mockRejectedValueOnce(new ApiError('Nickname is too long', 422));

    const [conflict] = getWriteConflicts();
    let failure: unknown;
    await act(async () => {
      failure = await conflict?.reapply().catch((caught: unknown) => caught);
    });

    expect(failure).toBeInstanceOf(ApiError);
    expect(getWriteConflicts()).toEqual([conflict]);
  });

  it('replaces the conflict when re-applying is refused again', async () => {
    const { edit } = await setup();
    write.mockImplementationOnce(async () => refuse());
    await edit('Bob');
    await waitFor(() => expect(getWriteConflicts()).toHaveLength(1));
    write.mockImplementationOnce(async () => refuse());

    const [first] = getWriteConflicts();
    await act(async () => {
      await first?.reapply();
    });

    expect(getWriteConflicts()).toHaveLength(1);
    expect(getWriteConflicts()[0]?.id).not.toBe(first?.id);
  });

  it('does not count a re-read that was paused offline as fresh', async () => {
    // refetchQueries resolves at once for a paused query, so the dialog
    // would otherwise claim the page shows the latest version.
    const { edit } = await setup();
    write.mockImplementationOnce(async () => {
      onlineManager.setOnline(false);
      return refuse();
    });
    try {
      await edit('Bob');
      await waitFor(() => expect(getWriteConflicts()).toHaveLength(1));
      expect(getWriteConflicts()[0]?.refreshed).toBe(false);
    } finally {
      onlineManager.setOnline(true);
    }
  });

  it('replays against the version it re-read even after the detail was evicted', async () => {
    // A dialog left open past the cache's gcTime must not replay without a
    // precondition.
    const { queryClient, edit } = await setup();
    write.mockImplementationOnce(async () => refuse());
    server.current = { resource: doc('Augusta', 'Countess'), etag: '"e9"' };
    await edit('Bob');
    await waitFor(() => expect(getWriteConflicts()).toHaveLength(1));
    queryClient.removeQueries({ queryKey: KEY, exact: true });
    write.mockResolvedValueOnce({ body: undefined, etag: '"e10"' });

    await act(async () => {
      await getWriteConflicts()[0]?.reapply();
    });

    expect(write).toHaveBeenLastCalledWith('"e9"', 'Bob');
  });

  it('can still re-read after the detail was evicted, when keeping mine is refused again', async () => {
    // The replay puts the evicted detail back; the successor conflict re-reads
    // it with no page mounted to say how.
    const { queryClient, edit, leaveAndEvict } = await setup();
    write.mockImplementationOnce(async () => refuse());
    server.current = { resource: doc('Augusta', 'Countess'), etag: '"e9"' };
    await edit('Bob');
    await waitFor(() => expect(getWriteConflicts()).toHaveLength(1));
    leaveAndEvict();
    write.mockImplementationOnce(async () => refuse());
    server.current = { resource: doc('Augusta', 'Gus'), etag: '"e11"' };

    await act(async () => {
      await getWriteConflicts()[0]?.reapply();
    });

    expect(getWriteConflicts()).toHaveLength(1);
    expect(getWriteConflicts()[0]).toMatchObject({
      refreshed: true,
      changed: ['Nickname'],
    });
    expect(readEtag(queryClient, KEY)).toBe('"e11"');
  });

  it('replays against the version it re-read while the revisited page is still loading it', async () => {
    // Back on the page after eviction, its first read in flight: the cache
    // holds the record but no data yet, so no tag either.
    const { queryClient, edit, leaveAndEvict, revisit } = await setup();
    write.mockImplementationOnce(async () => refuse());
    server.current = { resource: doc('Augusta', 'Countess'), etag: '"e9"' };
    await edit('Bob');
    await waitFor(() => expect(getWriteConflicts()).toHaveLength(1));
    leaveAndEvict();
    read.mockImplementationOnce(() => new Promise(() => undefined));
    revisit();
    await waitFor(() =>
      expect(queryClient.getQueryState(KEY)?.fetchStatus).toBe('fetching')
    );
    write.mockResolvedValueOnce({ body: undefined, etag: '"e10"' });

    await act(async () => {
      await getWriteConflicts()[0]?.reapply();
    });

    expect(write).toHaveBeenLastCalledWith('"e9"', 'Bob');
  });

  it('restarts a nested first read already in flight, rather than trusting it', async () => {
    // That read may have left before the change that refused the write.
    let landStale: (tags: { data: string[] }) => void = () => undefined;
    readTags.mockImplementationOnce(
      () => new Promise(resolve => (landStale = resolve))
    );
    const { result, edit } = await setup();
    write.mockImplementationOnce(async () => refuse());
    readTags.mockResolvedValueOnce({ data: ['climbing'] });

    await edit('Bob');
    await waitFor(() => expect(getWriteConflicts()).toHaveLength(1));
    landStale({ data: ['stale'] });

    expect(getWriteConflicts()[0]?.refreshed).toBe(true);
    await waitFor(() =>
      expect(result.current.tags.data).toEqual({ data: ['climbing'] })
    );
  });

  it('can try a failed re-read again after the detail was evicted', async () => {
    const { queryClient, edit, leaveAndEvict } = await setup();
    write.mockImplementationOnce(async () => refuse());
    read.mockRejectedValueOnce(new Error('offline'));
    await edit('Bob');
    await waitFor(() => expect(getWriteConflicts()).toHaveLength(1));
    leaveAndEvict();
    server.current = { resource: doc('Augusta', 'Countess'), etag: '"e9"' };

    await act(async () => {
      await getWriteConflicts()[0]?.retryRefresh();
    });

    expect(getWriteConflicts()[0]).toMatchObject({
      refreshed: true,
      changed: ['First name'],
    });
    expect(readEtag(queryClient, KEY)).toBe('"e9"');
  });

  it('keeps theirs by dismissing the conflict without writing', async () => {
    const { edit } = await setup();
    write.mockImplementationOnce(async () => refuse());
    await edit('Bob');
    await waitFor(() => expect(getWriteConflicts()).toHaveLength(1));

    act(() => dismissWriteConflict(getWriteConflicts()[0]?.id ?? -1));

    expect(getWriteConflicts()).toEqual([]);
    expect(write).toHaveBeenCalledTimes(1);
  });

  it('leaves other failures to the hook that made them', async () => {
    const { edit } = await setup();
    write.mockRejectedValue(new Error('offline'));

    await edit('Bob');

    expect(getWriteConflicts()).toEqual([]);
  });

  it('keeps every conflict when two re-reads overlap', async () => {
    const queryClient = new QueryClient();
    const pending: Array<() => void> = [];
    const refusedWriteTo = (id: string) => {
      const detailKey = ['contacts', 'detail', id];
      queryClient.setQueryData(detailKey, {
        resource: doc(id, ''),
        etag: null,
      });
      // A detail query whose re-read waits until the test lets it finish.
      queryClient
        .getQueryCache()
        .find({ queryKey: detailKey })
        ?.setOptions({
          queryKey: detailKey,
          queryFn: () =>
            new Promise(resolve =>
              pending.push(() => resolve({ resource: doc(id, ''), etag: null }))
            ),
        });
      return {
        meta: { conflict: { kind: 'contact', id, detailKey } },
        options: {},
      } as unknown as Mutation<unknown, unknown, unknown, unknown>;
    };
    const conflict = () =>
      new PreconditionFailedError('moved on', undefined, {});

    const first = handleWriteConflict(
      queryClient,
      conflict(),
      {},
      refusedWriteTo('1')
    );
    const second = handleWriteConflict(
      queryClient,
      conflict(),
      {},
      refusedWriteTo('2')
    );
    await waitFor(() => expect(pending).toHaveLength(2));
    // The later re-read lands first.
    pending[1]?.();
    pending[0]?.();
    await Promise.all([first, second]);

    expect(getWriteConflicts()).toHaveLength(2);
  });
});
