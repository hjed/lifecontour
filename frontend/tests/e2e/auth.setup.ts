/**
 * Playwright Auth Setup
 *
 * Runs once before all test projects to perform the real OAuth flow against Hydra
 * and save the authenticated browser state (cookies + localStorage) to a JSON file.
 * All test projects that depend on this setup project will start pre-authenticated.
 *
 * @see https://playwright.dev/docs/auth
 */

import { test as setup, expect } from '@playwright/test';
import {
  FRONTEND_TEST_LOGIN_URL,
  OAUTH_PUBLIC_TEST_PORT,
  OAUTH_UI_TEST_PORT,
} from './utils/frontend-test-config';

const AUTH_FILE = 'playwright/.auth/user.json';

setup('authenticate via OAuth', async ({ page }) => {
  console.log('🔐 [Auth Setup] Starting OAuth flow...');

  // Step 1: Navigate to login page and wait for OAuth button
  await page.goto(FRONTEND_TEST_LOGIN_URL);

  const oauthButton = page.locator('button:has-text("Continue with")').first();
  await expect(oauthButton).toBeVisible({ timeout: 15000 });
  await expect(oauthButton).toBeEnabled({ timeout: 10000 });

  // Step 2: Click OAuth button and wait for navigation away from login page
  await Promise.all([
    page.waitForURL((url: URL) => !url.toString().includes('/auth/login'), {
      timeout: 30000,
    }),
    oauthButton.click({ timeout: 30000 }),
  ]);

  let currentUrl = page.url();
  console.debug('🔐 [Auth Setup] URL after OAuth click:', currentUrl);

  // Step 3: Handle OAuth provider interaction
  // Hydra is configured with skip_consent: true, so it auto-redirects
  if (
    currentUrl.includes(`localhost:${OAUTH_PUBLIC_TEST_PORT}`) ||
    currentUrl.includes(`localhost:${OAUTH_UI_TEST_PORT}`) ||
    currentUrl.includes('hydra')
  ) {
    console.debug(
      '🔐 [Auth Setup] Redirected to Hydra, waiting for callback...'
    );

    await page.waitForURL(
      (url: URL) =>
        url.toString().includes('/auth/callback') ||
        url.toString().includes('/contacts'),
      { timeout: 30000 }
    );

    currentUrl = page.url();
    console.debug('🔐 [Auth Setup] URL after Hydra processing:', currentUrl);
  }

  // Step 4: Wait for callback to complete
  if (currentUrl.includes('/auth/callback')) {
    console.debug('🔐 [Auth Setup] Processing OAuth callback...');

    await page.waitForURL(
      (url: URL) => !url.toString().includes('/auth/callback'),
      { timeout: 30000 }
    );

    currentUrl = page.url();
    console.debug('🔐 [Auth Setup] URL after callback:', currentUrl);
  }

  // Step 5: Verify we're not stuck on the login page
  if (currentUrl.includes('/auth/login')) {
    throw new Error(
      'OAuth flow failed — still on login page. Is the OAuth provider configured?'
    );
  }

  // Step 6: Verify authentication via API
  await expect(async () => {
    const statusResponse = await page.request.get('/api/auth/status');
    expect(statusResponse.ok()).toBe(true);

    const authStatus = await statusResponse.json();
    expect(authStatus.authenticated).toBe(true);
    console.debug('🔐 [Auth Setup] Authenticated as:', authStatus.user?.email);
  }).toPass({ timeout: 10000 });

  // Step 7: Save authenticated state to file for reuse by all test projects
  await page.context().storageState({ path: AUTH_FILE });
  console.log('🔐 [Auth Setup] Auth state saved to', AUTH_FILE);
});
