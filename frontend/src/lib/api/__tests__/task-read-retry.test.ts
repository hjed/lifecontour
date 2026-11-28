import { retryReadUnlessRefused, TaskApiError } from '../tasks';

describe('retryReadUnlessRefused', () => {
  it.each([400, 404])('never retries a %i refusal', status => {
    const refusal = new TaskApiError('Refused', status, 'TASK_LIST_NOT_FOUND');

    expect(retryReadUnlessRefused(0, refusal)).toBe(false);
  });

  it.each([
    ['a server error', new TaskApiError('Failed', 500)],
    ['a request timeout', new TaskApiError('Timed out', 408)],
    ['a rate limit', new TaskApiError('Slow down', 429)],
    ['a network failure', new TypeError('Failed to fetch')],
  ])('retries %s up to three times', (_label, failure) => {
    expect(retryReadUnlessRefused(0, failure)).toBe(true);
    expect(retryReadUnlessRefused(2, failure)).toBe(true);
    expect(retryReadUnlessRefused(3, failure)).toBe(false);
  });
});
