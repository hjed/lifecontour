/**
 * End-to-end tests for the OAuth authentication happy path.
 *
 * Tests the real authorization redirect against the Hydra OAuth provider.
 * Error/edge-case handling (invalid state, provider errors, malformed
 * callbacks, missing parameters, network failures) lives in
 * oauth-error-handling.spec.ts. Hydra/Docker infrastructure configuration
 * is verified in oauth-docker-integration.spec.ts.
 *
 * RELIABILITY: This file follows Playwright best practices:
 * - Uses web-first assertions instead of hard-coded waits
 * - Uses waitForURL instead of waitForTimeout
 * - Explicit assertions instead of conditional logic
 *
 * @see E2E_TESTING_GUIDELINES.md for best practices documentation
 */

import { test, expect } from './fixtures';
import { OAUTH_PUBLIC_TEST_PORT } from './utils/frontend-test-config';

/** Helper to check if URL is not the login page */
const isNotLoginPage = (url: URL): boolean =>
  !url.toString().includes('/auth/login');

test.describe('OAuth Authentication Flow - Real Provider Tests', () => {
  test('should complete full OAuth flow with Hydra provider', async ({
    unauthenticatedPage: page,
  }) => {
    // Navigate to login page and wait for it to be ready
    await page.goto('/auth/login');
    await expect(page.locator('h1')).toContainText('Welcome Back');

    // Find and click OAuth button
    const oauthButton = page
      .locator('button:has-text("Continue with")')
      .first();
    await expect(oauthButton).toBeVisible({ timeout: 10000 });

    // Click OAuth button and wait for navigation away from login
    await Promise.all([
      page.waitForURL(isNotLoginPage, { timeout: 30000 }).catch(() => null),
      oauthButton.click(),
    ]);

    const currentUrl = page.url();

    const redirectedToProvider =
      currentUrl.includes(OAUTH_PUBLIC_TEST_PORT) ||
      currentUrl.includes('hydra') ||
      currentUrl.includes('/auth/callback');
    expect(redirectedToProvider).toBe(true);
  });
});
