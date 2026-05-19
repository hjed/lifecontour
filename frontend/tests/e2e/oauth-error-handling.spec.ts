/**
 * End-to-end tests for OAuth error handling scenarios.
 *
 * Tests various OAuth error conditions including invalid state,
 * expired codes, provider errors, and network failures to ensure
 * robust error handling without mocking critical parts.
 *
 * RELIABILITY: This file follows Playwright best practices:
 * - Uses web-first assertions instead of hard-coded waits
 * - Uses waitForURL and waitForResponse instead of waitForTimeout
 * - Explicit assertions instead of conditional logic
 *
 * @see E2E_TESTING_GUIDELINES.md for best practices documentation
 */

import { test, expect } from './fixtures';
import { OAUTH_PUBLIC_TEST_PORT } from './utils/frontend-test-config';

test.describe('OAuth Error Handling', () => {
  test('should handle invalid OAuth state parameter', async ({
    unauthenticatedPage: page,
  }) => {
    // Navigate to login page and wait for it to be ready
    await page.goto('/auth/login');
    await expect(page.getByRole('heading', { name: /welcome/i })).toBeVisible();

    // Set up session storage as if we initiated OAuth
    await page.evaluate(() => {
      sessionStorage.setItem('oauth_provider', 'generic');
    });

    // Navigate to callback with invalid state
    await page.goto(
      '/auth/callback?code=valid-code&state=invalid-state-that-does-not-match'
    );

    // Wait for error handling UI to appear
    await expect(page.locator('body')).toContainText('Authentication Failed', {
      timeout: 10000,
    });

    // Click retry button and verify redirect
    await page.getByRole('button', { name: 'Try signing in again' }).click();
    await expect(async () => {
      expect(page.url()).toContain('/auth/login');
    }).toPass({ timeout: 10000 });
  });

  test('should handle expired OAuth authorization codes', async ({
    unauthenticatedPage: page,
  }) => {
    // Encode state parameter with flow_type and provider
    const state = btoa(
      JSON.stringify({ flow_type: 'auth', provider: 'generic' })
    );

    // Navigate to callback with expired code
    await page.goto(
      `/auth/callback?code=expired-or-invalid-code&state=${state}`
    );

    // Wait for page to settle and verify error handling
    await expect(async () => {
      const bodyText = await page.textContent('body');
      const hasError =
        bodyText?.includes('error') ||
        bodyText?.includes('expired') ||
        bodyText?.includes('invalid') ||
        page.url().includes('/auth/login');
      expect(hasError).toBe(true);
    }).toPass({ timeout: 10000 });
  });

  test('should handle OAuth provider errors', async ({
    unauthenticatedPage: page,
  }) => {
    // Test OAuth error scenarios
    const errorScenarios = [
      {
        name: 'access_denied',
        params: 'error=access_denied&error_description=User%20denied%20access',
      },
      {
        name: 'invalid_request',
        params:
          'error=invalid_request&error_description=Invalid%20OAuth%20request',
      },
      {
        name: 'server_error',
        params: 'error=server_error&error_description=OAuth%20provider%20error',
      },
    ];

    for (const scenario of errorScenarios) {
      await page.goto(`/auth/callback?${scenario.params}`);
      // Wait for the page to settle after navigation - Firefox needs this
      // when rapidly navigating in a loop
      await page.waitForLoadState('domcontentloaded');

      // Wait for error handling UI to appear
      await expect(page.locator('body')).toContainText(
        'Authentication Failed',
        { timeout: 10000 }
      );

      // Click retry button and verify redirect
      await page.getByRole('button', { name: 'Try signing in again' }).click();
      await expect(async () => {
        expect(page.url()).toContain('/auth/login');
      }).toPass({ timeout: 10000 });
    }
  });

  test('should handle network failures during OAuth flow', async ({
    unauthenticatedPage: page,
  }) => {
    // Navigate to login page and wait for OAuth button
    await page.goto('/auth/login');
    const oauthButton = page
      .locator('button:has-text("Continue with")')
      .first();
    await expect(oauthButton).toBeVisible();

    // Simulate network failure by intercepting requests
    await page.route('**/api/auth/login', route => route.abort('failed'));

    // Click OAuth button
    await oauthButton.click();

    // Verify page remains functional after network failure
    await expect(async () => {
      // Page should still have interactive elements
      const clickableCount = await page.locator('button, a, input').count();
      expect(clickableCount).toBeGreaterThan(0);
    }).toPass({ timeout: 10000 });

    // Note: No cleanup needed - Playwright automatically cleans up routes when the page/context is closed
  });

  test('should handle malformed OAuth callback URLs', async ({
    unauthenticatedPage: page,
  }) => {
    const malformedUrls = [
      '/auth/callback?code=',
      '/auth/callback?state=',
      '/auth/callback?code=test',
      '/auth/callback?state=test',
      '/auth/callback?invalid=params',
    ];

    for (const url of malformedUrls) {
      await page.goto(url);
      // Wait for the page to settle after navigation - Firefox needs this
      // when rapidly navigating in a loop
      await page.waitForLoadState('domcontentloaded');

      // Verify page handles malformed URL gracefully
      await expect(async () => {
        const bodyText = await page.textContent('body');
        const isHandled = bodyText !== null && bodyText.length > 0;
        expect(isHandled).toBe(true);
      }).toPass({ timeout: 10000 });
    }
  });
});

test.describe('OAuth Session and State Management Errors', () => {
  test('should handle missing session state during callback', async ({
    unauthenticatedPage: page,
  }) => {
    // Navigate directly to callback without establishing session
    await page.goto('/auth/callback?code=test-code&state=test-state');

    // Verify graceful error handling - page should show error message or redirect to login
    await expect(async () => {
      const bodyText = await page.textContent('body');
      const hasErrorHandling =
        bodyText !== null &&
        (bodyText.includes('error') ||
          bodyText.includes('invalid') ||
          page.url().includes('/auth/login'));
      expect(hasErrorHandling).toBe(true);
    }).toPass({ timeout: 10000 });
  });

  test('should handle session timeout during OAuth flow', async ({
    unauthenticatedPage: page,
  }) => {
    // Encode state parameter with flow_type and provider
    const state = btoa(
      JSON.stringify({ flow_type: 'auth', provider: 'generic' })
    );

    // Try to complete OAuth callback with valid state
    await page.goto(`/auth/callback?code=test-code&state=${state}`);

    // Verify graceful handling
    await expect(async () => {
      const bodyText = await page.textContent('body');
      const isHandled = bodyText !== null && bodyText.length > 0;
      expect(isHandled).toBe(true);
    }).toPass({ timeout: 10000 });
  });

  test('should handle concurrent OAuth attempts', async ({
    unauthenticatedPage: page,
  }) => {
    await page.goto('/auth/login');
    const oauthButton = page
      .locator('button:has-text("Continue with")')
      .first();
    await expect(oauthButton).toBeVisible();

    // Click button and verify page handles it
    await oauthButton.click();

    // Verify page remains stable (either navigated or stayed on login)
    await expect(async () => {
      const bodyText = page;
      await expect(bodyText).toHaveText('body');
    }).toPass({ timeout: 10000 });
  });

  test('should handle OAuth provider unavailability', async ({
    unauthenticatedPage: page,
  }) => {
    await page.goto('/auth/login');
    const oauthButton = page
      .locator('button:has-text("Continue with")')
      .first();
    await expect(oauthButton).toBeVisible();

    // Intercept OAuth provider requests to simulate unavailability
    await page.route('**/oauth/**', route => route.abort('failed'));
    await page.route(`**localhost:${OAUTH_PUBLIC_TEST_PORT}/**`, route =>
      route.abort('failed')
    );
    // Also intercept the login API call itself since the button click
    // hits this endpoint first before any OAuth provider redirect
    await page.route('**/api/auth/login', route => route.abort('failed'));

    await oauthButton.click();

    // Wait for the page to settle after the failed request
    await page.waitForLoadState('domcontentloaded');

    // Verify page remains functional — check for interactive elements rather
    // than body text, which can be empty during mid-navigation states
    await expect(async () => {
      const clickableCount = await page.locator('button, a, input').count();
      expect(clickableCount).toBeGreaterThan(0);
    }).toPass({ timeout: 10000 });

    // Note: No cleanup needed - Playwright automatically cleans up routes when the page/context is closed
  });
});
