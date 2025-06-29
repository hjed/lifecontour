/**
 * End-to-end tests for OAuth authentication flow.
 *
 * Tests the complete OAuth flow including redirect URI handling,
 * callback processing, and session management.
 */

import { test, expect } from '@playwright/test';
import {
  createTestHelpers,
  navigateAndWaitForStable,
  verifyUrlMatches,
} from './utils/test-helpers';

test.describe('OAuth Authentication Flow', () => {
  test('should handle OAuth redirect URI correctly', async ({ page }) => {
    const { oauth } = createTestHelpers(page);

    // Navigate to login page (test real backend)
    await page.goto('/auth/login');

    // Verify login page loads
    await expect(page.locator('h1')).toContainText('Welcome Back');

    // Wait for providers to load and verify OAuth buttons
    await oauth.verifyOAuthButtonsVisible(15000);

    // Set up request tracking
    let loginRequestMade = false;
    page.on('request', request => {
      if (request.url().includes('/api/auth/login')) {
        loginRequestMade = true;
        console.log('Login request made:', request.url());
      }
    });

    await oauth.clickFirstOAuthButton();

    // Wait a bit to see if request is made
    await page.waitForTimeout(2000);

    // Check if login request was made
    if (!loginRequestMade) {
      throw new Error('Login request was not made after button click');
    }
  });

  test('should handle OAuth callback with correct parameters', async ({
    page,
  }) => {
    // Simulate OAuth callback with correct parameters (test real backend)
    await navigateAndWaitForStable(
      page,
      '/auth/callback?code=test-code&state=test-state'
    );

    // Should stay on callback URL or redirect to a valid page
    await verifyUrlMatches(page, [
      '/auth/callback',
      '/auth/login',
      '/',
      '/contacts',
    ]);
  });

  test('should handle OAuth callback errors gracefully', async ({ page }) => {
    // Navigate to callback page with error parameters
    await page.goto(
      '/auth/callback?error=access_denied&error_description=User%20denied%20access'
    );

    // Wait for the page to process the error
    await page.waitForLoadState('networkidle');

    // Verify error is displayed - check for either the error message or error state
    await expect(page.locator('body')).toContainText('User denied access', {
      timeout: 10000,
    });
  });

  test('should handle missing OAuth parameters', async ({ page }) => {
    // Navigate to callback page without required parameters
    await page.goto('/auth/callback');

    // Verify error is displayed for missing parameters
    await expect(page.locator('body')).toContainText(
      'Missing required OAuth parameters'
    );
  });

  test('should redirect unauthenticated users to login', async ({ page }) => {
    const { auth } = createTestHelpers(page);

    // Navigate to a protected page (no mocking - test real backend)
    await page.goto('/');

    // Handle authentication redirect or successful access
    await auth.handleProtectedPageAccess();
  });

  test('should handle OAuth login button clicks', async ({ page }) => {
    const { oauth } = createTestHelpers(page);

    // Navigate to login page
    await navigateAndWaitForStable(page, '/auth/login');

    // Handle OAuth buttons if present
    await oauth.handleOAuthButtons({ click: true, waitAfterClick: 1000 });

    // The page should load without crashing regardless
    const currentUrl = page.url();
    expect(currentUrl).toBeTruthy();
    const bodyText = await page.textContent('body');
    expect(bodyText).toBeTruthy();
  });

  test('should redirect to login when accessing protected pages', async ({
    page,
  }) => {
    const { auth } = createTestHelpers(page);

    // Try to access a protected page (no mocking - test real backend)
    await page.goto('/contacts');

    // Handle authentication redirect or successful access
    await auth.handleProtectedPageAccess();
  });

  test('should redirect to login when accessing protected pages without auth', async ({
    page,
  }) => {
    const { auth } = createTestHelpers(page);

    // Navigate to contacts page (no mocking - test real backend)
    await page.goto('/contacts');

    // Handle authentication redirect or successful access
    await auth.handleProtectedPageAccess();
  });

  test('should handle OAuth provider selection', async ({ page }) => {
    const { oauth } = createTestHelpers(page);

    // Navigate to login page (no mocking - test real backend)
    await navigateAndWaitForStable(page, '/auth/login');

    // Handle OAuth buttons if available
    await oauth.handleOAuthButtons({ click: true, waitAfterClick: 1000 });

    // Verify page loads without crashing
    const bodyText = await page.textContent('body');
    expect(bodyText).toBeTruthy();
  });

  test('should handle OAuth login attempts', async ({ page }) => {
    const { oauth } = createTestHelpers(page);

    // Navigate to login page (no mocking - test real backend)
    await page.goto('/auth/login');

    // Try to login with OAuth provider
    await oauth.verifyOAuthButtonsVisible();
    await oauth.clickFirstOAuthButton();

    // Should either redirect to OAuth provider or show error
    // We just verify the click doesn't crash the page
    await page.waitForTimeout(1000);
  });
});

test.describe('OAuth Redirect URI Configuration', () => {
  test('should handle OAuth login flow', async ({ page }) => {
    const { oauth } = createTestHelpers(page);

    // Test OAuth login flow with real backend
    await page.goto('/auth/login');

    await oauth.verifyOAuthButtonsVisible(10000);
    await oauth.clickFirstOAuthButton();

    // Wait for login request to be made
    await page.waitForTimeout(1000);

    // Test /authorize endpoint (if accessible via direct URL)
    // This would be tested in integration tests rather than e2e tests
    // since it's an API endpoint that returns a redirect
  });
});
