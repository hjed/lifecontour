/**
 * @jest-environment node
 */

import {
  ApiError,
  PreconditionFailedError,
  sendConditional,
} from '../conditional-request';

globalThis.fetch = jest.fn();
const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

const URL = '/api/contacts/1/fields/nickname';

function jsonResponse(
  body: unknown,
  status: number,
  headers: Record<string, string> = {}
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

function sentHeaders(): Headers {
  return new Headers(mockFetch.mock.calls[0]?.[1]?.headers);
}

describe('sendConditional', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it('sends If-Match when a tag is known', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ data: {} }, 200));

    await sendConditional(URL, {
      method: 'PATCH',
      body: { data: { value: 'Bob' } },
      ifMatch: '"e1"',
      fallbackMessage: 'failed',
    });

    expect(sentHeaders().get('If-Match')).toBe('"e1"');
    expect(sentHeaders().get('Content-Type')).toBe('application/json');
    expect(mockFetch.mock.calls[0]?.[1]).toMatchObject({
      method: 'PATCH',
      credentials: 'include',
      body: JSON.stringify({ data: { value: 'Bob' } }),
    });
  });

  it('sends no If-Match when no tag is known', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ data: {} }, 200));

    await sendConditional(URL, {
      method: 'PATCH',
      ifMatch: null,
      fallbackMessage: 'failed',
    });

    expect(sentHeaders().has('If-Match')).toBe(false);
  });

  it('returns the body and the ETag of a 200', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ data: { id: '1' } }, 200, { ETag: '"e2"' })
    );

    const result = await sendConditional<{ data: { id: string } }>(URL, {
      method: 'PATCH',
      ifMatch: '"e1"',
      fallbackMessage: 'failed',
    });

    expect(result).toEqual({ body: { data: { id: '1' } }, etag: '"e2"' });
  });

  it('reads the ETag of a 204 without reading its empty body', async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(null, { status: 204, headers: { ETag: '"e3"' } })
    );

    const result = await sendConditional(URL, {
      method: 'DELETE',
      ifMatch: '"e2"',
      fallbackMessage: 'failed',
    });

    expect(result).toEqual({ body: undefined, etag: '"e3"' });
  });

  it('reports a missing ETag as null', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ data: {} }, 200));

    const result = await sendConditional(URL, {
      method: 'PATCH',
      ifMatch: null,
      fallbackMessage: 'failed',
    });

    expect(result.etag).toBeNull();
  });

  it('turns a 412 into a PreconditionFailedError carrying the current tag', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(
        {
          errors: [
            {
              status: '412',
              code: 'PRECONDITION_FAILED',
              title: 'Precondition Failed',
              detail: 'The contact has changed since it was read',
              meta: {
                resource_type: 'contacts',
                resource_id: '1',
                current_etag: '"e9"',
              },
            },
          ],
        },
        412
      )
    );

    const error = await sendConditional(URL, {
      method: 'PATCH',
      ifMatch: '"e1"',
      fallbackMessage: 'failed',
    }).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(PreconditionFailedError);
    expect(error).toMatchObject({
      status: 412,
      code: 'PRECONDITION_FAILED',
      currentEtag: '"e9"',
      message: 'The contact has changed since it was read',
    });
  });

  it('turns any other refusal into an ApiError with its code and meta', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(
        {
          errors: [
            {
              code: 'VALIDATION_ERROR',
              detail: 'Nickname is too long',
              meta: { field: 'nickname' },
            },
          ],
        },
        422
      )
    );

    const error = await sendConditional(URL, {
      method: 'PATCH',
      ifMatch: null,
      fallbackMessage: 'failed',
    }).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).not.toBeInstanceOf(PreconditionFailedError);
    expect(error).toMatchObject({
      status: 422,
      code: 'VALIDATION_ERROR',
      meta: { field: 'nickname' },
      message: 'Nickname is too long',
    });
  });

  it('falls back to the given message when the error body is not JSON', async () => {
    mockFetch.mockResolvedValueOnce(
      new Response('<html>Bad Gateway</html>', { status: 502 })
    );

    const error = await sendConditional(URL, {
      method: 'PATCH',
      ifMatch: null,
      fallbackMessage: 'failed',
    }).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 502, message: 'failed' });
  });
});
