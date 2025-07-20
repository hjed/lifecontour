/**
 * Playwright E2E tests for search functionality.
 *
 * Converted to use the advanced fixture-based testing system.
 * Tests search functionality with deterministic authentication states.
 */

import { test, expect } from './fixtures';

test.describe('Search Functionality - Unauthenticated', () => {
  test('should redirect to login when accessing search without authentication', async ({
    unauthenticatedPage,
  }) => {
    // Try to access contacts page with search parameter
    await unauthenticatedPage.goto('/contacts?search=test');

    // Should redirect to login (guaranteed by fixture)
    await expect(unauthenticatedPage).toHaveURL(/\/auth\/login/);

    // Verify login page loads correctly
    await expect(
      unauthenticatedPage.getByRole('heading', { name: 'Welcome Back' })
    ).toBeVisible();

    // Verify OAuth buttons are present
    const oauthButtons = unauthenticatedPage.locator(
      'button:has-text("Continue with")'
    );
    await expect(oauthButtons.first()).toBeVisible();
  });

  test('should redirect to login when accessing global search', async ({
    unauthenticatedPage,
  }) => {
    // Try to access any search functionality
    await unauthenticatedPage.goto('/search?q=test');

    // Should redirect to login page (guaranteed by fixture)
    await expect(unauthenticatedPage).toHaveURL(/\/auth\/login/);

    // Should show login page content
    await expect(
      unauthenticatedPage.getByRole('heading', { name: 'Welcome Back' })
    ).toBeVisible();
  });
});

test.describe('Search Functionality - Authenticated', () => {
  test('should allow search when authenticated', async ({
    authenticatedPage,
  }) => {
    // Access contacts page with search parameter
    await authenticatedPage.goto('/contacts?search=test');

    // Should stay on contacts page (not redirect to login)
    await expect(authenticatedPage).toHaveURL(/\/contacts/);
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // Page should load successfully
    const bodyText = await authenticatedPage.textContent('body');
    expect(bodyText).toBeTruthy();
  });
});
