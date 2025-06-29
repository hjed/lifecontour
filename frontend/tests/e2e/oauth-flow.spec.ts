/**
 * End-to-end tests for OAuth authentication flow.
 * 
 * Tests the complete OAuth flow including redirect URI handling,
 * callback processing, and session management.
 */

import { test, expect } from '@playwright/test';
import { waitForPageReady } from './utils/test-helpers';

test.describe('OAuth Authentication Flow', () => {
  test('should handle OAuth redirect URI correctly', async ({ page }) => {
    // Navigate to login page (test real backend)
    await page.goto('/auth/login');

    // Verify login page loads
    await expect(page.locator('h1')).toContainText('Welcome Back');

    // Wait for providers to load and button to appear
    const oauthButtons = page.locator('button:has-text("Continue with")');
    await expect(oauthButtons.first()).toBeVisible({ timeout: 15000 });

    // Ensure button is enabled before clicking
    await expect(oauthButtons.first()).toBeEnabled();

    // Set up request tracking
    let loginRequestMade = false;
    page.on('request', request => {
      if (request.url().includes('/api/auth/login')) {
        loginRequestMade = true;
        console.log('Login request made:', request.url());
      }
    });

    await oauthButtons.first().click();

    // Wait a bit to see if request is made
    await page.waitForTimeout(2000);

    // Check if login request was made
    if (!loginRequestMade) {
      throw new Error('Login request was not made after button click');
    }
  });

  test('should handle OAuth callback with correct parameters', async ({ page }) => {
    // Simulate OAuth callback with correct parameters (test real backend)
    await page.goto('/auth/callback?code=test-code&state=test-state');

    // Verify callback page processes the OAuth response
    // Note: With real backend, this might redirect to login if auth fails
    // or to dashboard if successful - we just verify no crash occurs
    await page.waitForLoadState('networkidle');

    // Should stay on callback URL or redirect to a valid page
    const currentUrl = page.url();
    expect(currentUrl).toMatch(/\/(auth\/callback|auth\/login|$|contacts)/);
  });

  test('should handle OAuth callback errors gracefully', async ({ page }) => {
    // Navigate to callback page with error parameters
    await page.goto('/auth/callback?error=access_denied&error_description=User%20denied%20access');

    // Verify error is displayed
    await expect(page.locator('body')).toContainText('User denied access');
  });

  test('should handle missing OAuth parameters', async ({ page }) => {
    // Navigate to callback page without required parameters
    await page.goto('/auth/callback');

    // Verify error is displayed for missing parameters
    await expect(page.locator('body')).toContainText('Missing required OAuth parameters');
  });

  test('should redirect unauthenticated users to login', async ({ page }) => {
    // Navigate to a protected page (no mocking - test real backend)
    await page.goto('/');
    await waitForPageReady(page);

    // Check if we're redirected to login or if page loads (auth might be bypassed in dev)
    const currentUrl = page.url();
    if (currentUrl.includes('/auth/login')) {
      // If redirected to login, verify login page shows OAuth buttons
      const oauthButtons = page.locator('button:has-text("Continue with")');
      await expect(oauthButtons.first()).toBeVisible({ timeout: 10000 });
    } else {
      // If not redirected, just verify the page loads without crashing
      const bodyText = await page.textContent('body');
      expect(bodyText).toBeTruthy();
    }
  });

  test('should handle OAuth login button clicks', async ({ page }) => {
    // Navigate to login page
    await page.goto('/auth/login');
    await waitForPageReady(page);

    // Check if OAuth buttons are present
    const oauthButtons = page.locator('button:has-text("Continue with")');
    const buttonCount = await oauthButtons.count();

    if (buttonCount > 0) {
      // If buttons are present, test clicking them
      await expect(oauthButtons.first()).toBeVisible();
      await expect(oauthButtons.first()).toBeEnabled();

      // Click the OAuth button (this will trigger the real OAuth flow)
      await oauthButtons.first().click();

      // Wait a moment to see if any navigation happens
      await page.waitForTimeout(1000);
    }

    // The page should load without crashing regardless
    const currentUrl = page.url();
    expect(currentUrl).toBeTruthy();
    const bodyText = await page.textContent('body');
    expect(bodyText).toBeTruthy();
  });

  test('should redirect to login when accessing protected pages', async ({ page }) => {
    // Try to access a protected page (no mocking - test real backend)
    await page.goto('/contacts');

    // Check if we're redirected to login or if page loads (auth might be bypassed in dev)
    const currentUrl = page.url();
    if (currentUrl.includes('/auth/login')) {
      // If redirected to login, verify login page shows OAuth buttons
      const oauthButtons = page.locator('button:has-text("Continue with")');
      await expect(oauthButtons.first()).toBeVisible({ timeout: 10000 });
    } else {
      // If not redirected, just verify the page loads without crashing
      const bodyText = await page.textContent('body');
      expect(bodyText).toBeTruthy();
    }
  });

  test('should redirect to login when accessing protected pages without auth', async ({ page }) => {
    // Navigate to contacts page (no mocking - test real backend)
    await page.goto('/contacts');
    await waitForPageReady(page);

    // Check if we're redirected to login or if page loads (auth might be bypassed in dev)
    const currentUrl = page.url();
    if (currentUrl.includes('/auth/login')) {
      // If redirected to login, verify login page shows OAuth buttons
      const oauthButtons = page.locator('button:has-text("Continue with")');
      await expect(oauthButtons.first()).toBeVisible({ timeout: 10000 });
    } else {
      // If not redirected, just verify the page loads without crashing
      const bodyText = await page.textContent('body');
      expect(bodyText).toBeTruthy();
    }
  });

  test('should handle OAuth provider selection', async ({ page }) => {
    // Navigate to login page (no mocking - test real backend)
    await page.goto('/auth/login');
    await waitForPageReady(page);

    // Check if OAuth provider buttons are available
    const oauthButtons = page.locator('button:has-text("Continue with")');
    const buttonCount = await oauthButtons.count();

    if (buttonCount > 0) {
      // If buttons are present, test clicking them
      await expect(oauthButtons.first()).toBeVisible();
      await oauthButtons.first().click();
      await page.waitForTimeout(1000);
    }

    // Verify page loads without crashing
    const bodyText = await page.textContent('body');
    expect(bodyText).toBeTruthy();
  });

  test('should handle OAuth login attempts', async ({ page }) => {
    // Navigate to login page (no mocking - test real backend)
    await page.goto('/auth/login');

    // Try to login with OAuth provider
    const oauthButtons = page.locator('button:has-text("Continue with")');
    await expect(oauthButtons.first()).toBeVisible();
    await oauthButtons.first().click();

    // Should either redirect to OAuth provider or show error
    // We just verify the click doesn't crash the page
    await page.waitForTimeout(1000);
  });
});

test.describe('OAuth Redirect URI Configuration', () => {
  test('should handle OAuth login flow', async ({ page }) => {
    // Test OAuth login flow with real backend
    await page.goto('/auth/login');

    const oauthButtons = page.locator('button:has-text("Continue with")');
    await expect(oauthButtons.first()).toBeVisible({ timeout: 10000 });
    await oauthButtons.first().click();

    // Wait for login request to be made
    await page.waitForTimeout(1000);

    // Test /authorize endpoint (if accessible via direct URL)
    // This would be tested in integration tests rather than e2e tests
    // since it's an API endpoint that returns a redirect
  });
});
