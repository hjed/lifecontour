/**
 * Conditional writes: the one place a contact or journal write is sent.
 *
 * The backend guards every write to a contact or journal aggregate with
 * `If-Match` and answers each one with the aggregate's new `ETag` — a `204`
 * included (`docs/architecture/api-design.md` → Conditional Writes). This
 * module sends the precondition, hands back the tag the write committed, and
 * turns a refusal into a typed error, so no hook has to read headers or parse
 * error bodies itself.
 */

import type { JsonApiErrorResponse, JsonApiMeta } from '@/types/api';

/** A request the API refused, carrying what the refusal said. */
export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly meta?: JsonApiMeta;

  constructor(
    message: string,
    status: number,
    code?: string,
    meta?: JsonApiMeta
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.meta = meta;
  }
}

/**
 * A conditional write refused because the aggregate moved on since its tag
 * was read. Nothing was written.
 *
 * `currentEtag` is the aggregate's version now. It is reported, not trusted:
 * the client re-reads the aggregate rather than retrying blind with it, since
 * retrying with the new tag would overwrite the change the user has not seen.
 */
export class PreconditionFailedError extends ApiError {
  readonly currentEtag: string | null;

  constructor(
    message: string,
    code: string | undefined,
    meta: JsonApiMeta | undefined
  ) {
    super(message, 412, code, meta);
    this.name = 'PreconditionFailedError';
    const currentEtag = meta?.current_etag;
    this.currentEtag = typeof currentEtag === 'string' ? currentEtag : null;
  }
}

/** A write's response body, with the aggregate version it committed. */
export interface ConditionalResult<T> {
  body: T;
  etag: string | null;
}

export interface ConditionalRequest {
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  /** Serialised as JSON. Omitted for a request with no body. */
  body?: unknown;
  /** The tag to guard the write with; `null` writes unconditionally. */
  ifMatch: string | null;
  /** The message to show when the refusal carries none of its own. */
  fallbackMessage: string;
}

/**
 * Turns a failed response into the error the caller sees.
 *
 * The body is parsed defensively: a gateway error page must still produce a
 * usable message rather than a `SyntaxError` from `response.json()`.
 */
async function toApiError(
  response: Response,
  fallbackMessage: string
): Promise<ApiError> {
  let detail: string | undefined;
  let code: string | undefined;
  let meta: JsonApiMeta | undefined;

  try {
    const body = (await response.json()) as JsonApiErrorResponse;
    const error = body.errors?.[0];
    detail = error?.detail;
    code = error?.code;
    meta = error?.meta;
  } catch {
    // No body, or one that is not JSON. The status is all there is to go on.
  }

  const message = detail || fallbackMessage;
  if (response.status === 412) {
    return new PreconditionFailedError(message, code, meta);
  }
  return new ApiError(message, response.status, code, meta);
}

/**
 * Sends one write, guarded by `ifMatch` when a tag is known.
 *
 * `T` is the response body; leave it as `undefined` for a route that answers
 * `204`, whose body is never read — calling `json()` on it throws.
 */
export async function sendConditional<T = undefined>(
  url: string,
  { method, body, ifMatch, fallbackMessage }: ConditionalRequest
): Promise<ConditionalResult<T>> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (ifMatch !== null) {
    headers['If-Match'] = ifMatch;
  }

  const response = await fetch(url, {
    method,
    credentials: 'include',
    headers,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });

  if (!response.ok) {
    throw await toApiError(response, fallbackMessage);
  }

  const etag = response.headers.get('ETag');
  if (response.status === 204) {
    // The caller named `T` as `undefined` for a 204 route; there is no body.
    return { body: undefined as T, etag };
  }
  return { body: (await response.json()) as T, etag };
}
