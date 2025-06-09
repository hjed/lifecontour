/**
 * End-to-end tests for authentication functionality.
 *
 * Tests OAuth login flow, session management, and protected route access.
 * These tests define the expected behavior for ITER1-004 authentication UI.
 */

import { test, expect } from '@playwright/test';
import { LoginPage } from './pages/login-page';
import { ContactsPage } from './pages/contacts-page';
import { setupApiMocks } from './utils/api-mocks';

test.describe('Authentication Flow', () => {
  let loginPage: LoginPage;
  let contactsPage: ContactsPage;

  test.beforeEach(async ({ page }) => {
    loginPage = new LoginPage(page);
    contactsPage = new ContactsPage(page);

    // Set up API mocks for consistent testing
    await setupApiMocks(page);
  });

  test('should display login page with OAuth providers', async ({
    page,
    browserName,
  }) => {
    await loginPage.navigateToLogin();

    // Wait for providers to load (WebKit needs more time)
    const waitTime = browserName === 'webkit' ? 3000 : 1000;
    await page.waitForTimeout(waitTime);

    // Verify login form is visible
    expect(await loginPage.isLoginFormVisible()).toBe(true);

    // Verify OAuth providers are displayed
    expect(await loginPage.areOAuthProvidersVisible()).toBe(true);

    // Verify expected providers are available
    const providers = await loginPage.getAvailableProviders();
    expect(providers).toContain('github');
    expect(providers).toContain('microsoft');

    // Verify page accessibility
    await loginPage.verifyLoginPageAccessibility();
  });

  test('should redirect unauthenticated users to login', async () => {
    // Try to access protected contacts page without authentication
    await loginPage.verifyProtectedRouteRedirection('/contacts');

    // Verify we're on the login page
    expect(await loginPage.isLoginFormVisible()).toBe(true);
  });

  test('should complete OAuth login flow successfully', async () => {
    await loginPage.navigateToLogin();

    // Perform OAuth login with GitHub
    await loginPage.performOAuthLogin('github');

    // Should be redirected to home page after successful login
    expect(await loginPage.isUserLoggedIn()).toBe(true);

    // Verify user name is displayed
    const userName = await loginPage.getLoggedInUserName();
    expect(userName).toBeTruthy();

    // Should be able to access protected routes
    await contactsPage.navigateToContacts();
    expect(await contactsPage.isContactsListVisible()).toBe(true);
  });

  test('should maintain session after page refresh', async () => {
    await loginPage.navigateToLogin();
    await loginPage.performOAuthLogin('github');

    // Verify session persistence
    await loginPage.verifySessionPersistence();

    // Should still have access to protected routes
    await contactsPage.navigateToContacts();
    expect(await contactsPage.isContactsListVisible()).toBe(true);
  });

  test('should logout user successfully', async () => {
    await loginPage.navigateToLogin();
    await loginPage.performOAuthLogin('github');

    // Verify user is logged in
    expect(await loginPage.isUserLoggedIn()).toBe(true);

    // Logout user
    await loginPage.logout();

    // Verify user is logged out
    expect(await loginPage.isUserLoggedIn()).toBe(false);

    // Should be redirected to login page when accessing protected routes
    await loginPage.verifyProtectedRouteRedirection('/contacts');
  });

  test('should handle authentication errors gracefully', async () => {
    // Mock authentication error
    await loginPage.page.route('**/api/auth/callback**', async route => {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({
          errors: [
            {
              status: '400',
              title: 'Authentication failed',
              detail: 'Invalid OAuth callback',
            },
          ],
        }),
      });
    });

    await loginPage.navigateToLogin();
    await loginPage.clickOAuthProvider('github');

    // Should display error message
    expect(await loginPage.hasAuthError()).toBe(true);

    const errorMessage = await loginPage.getAuthErrorMessage();
    expect(errorMessage).toContain('Authentication failed');
  });

  test('should work on mobile devices', async () => {
    await loginPage.navigateToLogin();

    // Test responsive login form
    await loginPage.testResponsiveLogin();

    // Test OAuth login on mobile
    await loginPage.setViewportSize(375, 667); // iPhone size
    await loginPage.performOAuthLogin('github');

    // Should work the same on mobile
    expect(await loginPage.isUserLoggedIn()).toBe(true);
  });

  test('should support multiple OAuth providers', async () => {
    await loginPage.navigateToLogin();

    // Test GitHub login
    await loginPage.performOAuthLogin('github');
    expect(await loginPage.isUserLoggedIn()).toBe(true);

    // Logout and test Microsoft login
    await loginPage.logout();
    await loginPage.navigateToLogin();
    await loginPage.performOAuthLogin('microsoft');
    expect(await loginPage.isUserLoggedIn()).toBe(true);
  });

  test('should handle network errors during authentication', async () => {
    // Mock network error
    await loginPage.page.route('**/api/auth/providers', async route => {
      await route.abort('failed');
    });

    await loginPage.navigateToLogin();

    // Should handle the error gracefully
    // The exact behavior depends on implementation, but should not crash
    await expect(loginPage.page).not.toHaveTitle(/Error/);
  });

  test('should redirect to intended page after login', async () => {
    // Try to access contacts page without authentication
    await contactsPage.navigateToContacts();

    // Should be redirected to login
    expect(await loginPage.isLoginFormVisible()).toBe(true);

    // Complete login
    await loginPage.performOAuthLogin('github');

    // Should be redirected back to contacts page
    expect(await contactsPage.isContactsListVisible()).toBe(true);
  });
});
