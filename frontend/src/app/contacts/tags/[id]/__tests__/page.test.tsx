/**
 * @jest-environment jsdom
 */

/**
 * Tests for the legacy /contacts/tags/[id] route redirect.
 *
 * This page now redirects to /contacts?tag=<id> for the unified contacts
 * list experience. The redirect is a server component that calls next/navigation
 * redirect(), so we test it by verifying the function throws NEXT_REDIRECT.
 */

import { redirect } from 'next/navigation';

jest.mock('next/navigation', () => ({
  redirect: jest.fn(),
}));

const mockRedirect = redirect as jest.MockedFunction<typeof redirect>;

describe('TagPageRedirect', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should redirect to /contacts?tag=<id>', async () => {
    // Dynamically import after mocking
    const { default: TagPageRedirect } = await import('../page');

    await TagPageRedirect({ params: Promise.resolve({ id: '42' }) });

    expect(mockRedirect).toHaveBeenCalledWith('/contacts?tag=42');
  });

  it('should redirect with the correct tag id', async () => {
    const { default: TagPageRedirect } = await import('../page');

    await TagPageRedirect({ params: Promise.resolve({ id: '7' }) });

    expect(mockRedirect).toHaveBeenCalledWith('/contacts?tag=7');
  });
});
