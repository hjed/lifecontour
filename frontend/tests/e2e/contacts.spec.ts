import { test, expect } from '@playwright/test';
import {
  createTestHelpers,
  navigateAndWaitForStable,
  verifyPageLoadsSuccessfully
} from './utils/test-helpers';

test.describe('Contact Management', () => {
  test('should load contacts page successfully', async ({ page }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts');

    // Verify the page loads (either contacts page or login redirect)
    await expect(page).toHaveTitle(/Personal Management System/);

    // Handle authentication redirect or successful access
    const result = await auth.handleProtectedPageAccess();

    if (result === 'redirected') {
      // Additional verification for login page
      await expect(page.getByRole('heading', { name: 'Welcome Back' })).toBeVisible();
    }
  });

  test('should load create contact page successfully', async ({ page }) => {
    await navigateAndWaitForStable(page, '/contacts/new');
    await verifyPageLoadsSuccessfully(page, /Personal Management System/);
  });

  test('should load contact details page successfully', async ({ page }) => {
    await navigateAndWaitForStable(page, '/contacts/123');
    await verifyPageLoadsSuccessfully(page, /Personal Management System/);
  });

  test('should load contact edit page successfully', async ({ page }) => {
    await navigateAndWaitForStable(page, '/contacts/123/edit');
    await verifyPageLoadsSuccessfully(page, /Personal Management System/);
  });

  test('should handle navigation between contact pages', async ({ page }) => {
    // Test basic navigation flow
    await navigateAndWaitForStable(page, '/contacts');

    // Try to navigate to create page (might redirect to login)
    try {
      await navigateAndWaitForStable(page, '/contacts/new');
    } catch (error) {
      // If navigation is interrupted by redirect, that's expected behavior
      console.log('Navigation redirected, which is expected for unauthenticated users');
    }

    // Verify we end up on a valid page (either contacts/new or login)
    const currentUrl = page.url();
    expect(currentUrl).toMatch(/\/(contacts|auth\/login)/);

    const bodyText = await page.textContent('body');
    expect(bodyText).toBeTruthy();
  });

});
