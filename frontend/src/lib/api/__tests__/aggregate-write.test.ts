import { QueryClient } from '@tanstack/react-query';
import { ApiError, PreconditionFailedError } from '../conditional-request';
import {
  aggregateScopeId,
  aggregateWrite,
  sendGuarded,
} from '../aggregate-write';
import {
  readEtag,
  storeEtag,
  updateResource,
  type Versioned,
} from '../versioned-cache';

const KEY = ['contacts', 'detail', '1'] as const;
const REF = { kind: 'contact', id: '1', detailKey: KEY } as const;

interface Resource {
  name: string;
}

function seeded(etag: string | null = '"e1"'): QueryClient {
  const queryClient = new QueryClient();
  queryClient.setQueryData<Versioned<Resource>>(KEY, {
    resource: { name: 'Ada' },
    etag,
  });
  return queryClient;
}

describe('versioned cache', () => {
  it('stores a new tag and leaves the resource alone', () => {
    const queryClient = seeded();

    storeEtag(queryClient, KEY, '"e2"');

    expect(queryClient.getQueryData(KEY)).toEqual({
      resource: { name: 'Ada' },
      etag: '"e2"',
    });
  });

  it('does not create an entry for an aggregate nobody has read', () => {
    const queryClient = new QueryClient();

    storeEtag(queryClient, KEY, '"e2"');

    expect(queryClient.getQueryData(KEY)).toBeUndefined();
    expect(readEtag(queryClient, KEY)).toBeNull();
  });

  it('updates the resource and leaves the tag alone', () => {
    const queryClient = seeded();

    updateResource<Resource>(queryClient, KEY, resource => ({
      ...resource,
      name: 'Augusta',
    }));

    expect(queryClient.getQueryData(KEY)).toEqual({
      resource: { name: 'Augusta' },
      etag: '"e1"',
    });
  });
});

describe('sendGuarded', () => {
  it('sends the cached tag and stores the one the write returns', async () => {
    const queryClient = seeded();
    const send = jest.fn().mockResolvedValue({ body: 'ok', etag: '"e2"' });

    const body = await sendGuarded(queryClient, KEY, send);

    expect(send).toHaveBeenCalledWith('"e1"');
    expect(body).toBe('ok');
    expect(readEtag(queryClient, KEY)).toBe('"e2"');
  });

  it('writes unconditionally when no tag is cached', async () => {
    const queryClient = new QueryClient();
    const send = jest.fn().mockResolvedValue({ body: undefined, etag: null });

    await sendGuarded(queryClient, KEY, send);

    expect(send).toHaveBeenCalledWith(null);
  });

  it('cancels an in-flight read of the aggregate before reading its tag', async () => {
    const queryClient = seeded();
    const cancel = jest.spyOn(queryClient, 'cancelQueries');
    const send = jest.fn().mockResolvedValue({ body: undefined, etag: '"e2"' });

    await sendGuarded(queryClient, KEY, send);

    expect(cancel).toHaveBeenCalledWith({ queryKey: KEY, exact: true });
    expect(cancel.mock.invocationCallOrder[0]).toBeLessThan(
      send.mock.invocationCallOrder[0] ?? 0
    );
  });
});

describe('sendGuarded and reads that overlap the write', () => {
  it('cancels a read started while the write was in flight before storing its tag', async () => {
    // A read that began before the write committed would land afterwards
    // with the old body and tag, and the next edit would conflict with this
    // page's own write.
    const queryClient = seeded();
    const cancel = jest.spyOn(queryClient, 'cancelQueries');
    const send = jest.fn().mockResolvedValue({ body: undefined, etag: '"e2"' });

    await sendGuarded(queryClient, KEY, send);

    expect(cancel).toHaveBeenCalledTimes(2);
    expect(cancel.mock.invocationCallOrder[1]).toBeGreaterThan(
      send.mock.invocationCallOrder[0] ?? Infinity
    );
    expect(readEtag(queryClient, KEY)).toBe('"e2"');
  });
});

describe('aggregateWrite', () => {
  const options = aggregateWrite(REF, (value: string) => `Name → ${value}`);

  it('scopes every write to one aggregate together', () => {
    expect(options.scope).toEqual({ id: aggregateScopeId('contact', '1') });
    expect(aggregateScopeId('contact', '1')).not.toBe(
      aggregateScopeId('journal', '1')
    );
  });

  it('describes the attempted change for the conflict dialog', () => {
    expect(options.meta.conflict.describe?.('Bob')).toBe('Name → Bob');
    expect(options.meta.conflict.detailKey).toBe(KEY);
  });

  it('never retries a refusal, but retries a server error once', () => {
    const retry = options.retry;

    expect(retry(0, new PreconditionFailedError('moved', undefined, {}))).toBe(
      false
    );
    expect(retry(0, new ApiError('bad', 422))).toBe(false);
    expect(retry(0, new ApiError('down', 503))).toBe(true);
    expect(retry(0, new TypeError('network'))).toBe(true);
    expect(retry(1, new TypeError('network'))).toBe(false);
  });
});
