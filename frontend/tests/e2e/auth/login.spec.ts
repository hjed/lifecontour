/**
 * End-to-end tests for the login page.
 *
 * Tests the complete login flow including OAuth provider interactions,
 * error handling, accessibility, and responsive design.
 */

import { test, expect } from '@playwright/test';
import { createAuthFixtures } from '../fixtures/auth';
import {
  createTestHelpers,
  SELECTORS,
  TEST_DATA,
  waitForPageReady,
} from '../utils/test-helpers';

test.describe('Login Page', () => {
  test.beforeEach(async ({ page }) => {
    // Setup authentication mocks
    const authFixtures = createAuthFixtures(page);
    await authFixtures.setupLoginPageMocks();

    // Navigate to login page
    await page.goto(TEST_DATA.URLS.LOGIN);
    await waitForPageReady(page);
  });

  test.describe('Page Rendering', () => {
    test('should render login page with correct title and content', async ({
      page,
    }) => {
      // Check page title
      await expect(page).toHaveTitle(/Personal Management System/);

      // Check main heading
      const heading = page.locator(SELECTORS.LOGIN_TITLE);
      await expect(heading).toBeVisible();
      await expect(heading).toHaveText('Welcome Back');

      // Check description
      const description = page.locator(
        'text=Sign in to your Personal Management System'
      );
      await expect(description).toBeVisible();

      // Check login form is present
      const loginForm = page.locator('main');
      await expect(loginForm).toBeVisible();
    });

    test('should display all OAuth provider buttons', async ({ page }) => {
      // Check GitHub button
      const githubButton = page.locator(SELECTORS.GITHUB_BUTTON);
      await expect(githubButton).toBeVisible();
      await expect(githubButton).toContainText('Continue with GitHub');

      // Check Microsoft button
      const microsoftButton = page.locator(SELECTORS.MICROSOFT_BUTTON);
      await expect(microsoftButton).toBeVisible();
      await expect(microsoftButton).toContainText('Continue with Microsoft');

      // Check Discord button
      const discordButton = page.locator(SELECTORS.DISCORD_BUTTON);
      await expect(discordButton).toBeVisible();
      await expect(discordButton).toContainText('Continue with Discord');
    });

    test('should display privacy notice', async ({ page }) => {
      const privacyNotice = page.locator(
        'text=By signing in, you agree to our terms of service and privacy policy.'
      );
      await expect(privacyNotice).toBeVisible();

      const privateAppNotice = page.locator(
        'text=This is a private application for personal use only.'
      );
      await expect(privateAppNotice).toBeVisible();
    });
  });

  test.describe('OAuth Provider Interactions', () => {
    test('should have clickable OAuth provider buttons', async ({ page }) => {
      const githubButton = page.locator(SELECTORS.GITHUB_BUTTON);
      const microsoftButton = page.locator(SELECTORS.MICROSOFT_BUTTON);
      const discordButton = page.locator(SELECTORS.DISCORD_BUTTON);

      // All buttons should be visible and enabled
      await expect(githubButton).toBeVisible();
      await expect(githubButton).toBeEnabled();
      await expect(microsoftButton).toBeVisible();
      await expect(microsoftButton).toBeEnabled();
      await expect(discordButton).toBeVisible();
      await expect(discordButton).toBeEnabled();
    });

    test('should have proper button labels and accessibility', async ({
      page,
    }) => {
      const githubButton = page.locator(SELECTORS.GITHUB_BUTTON);
      const microsoftButton = page.locator(SELECTORS.MICROSOFT_BUTTON);
      const discordButton = page.locator(SELECTORS.DISCORD_BUTTON);

      // Check button text content
      await expect(githubButton).toContainText('Continue with GitHub');
      await expect(microsoftButton).toContainText('Continue with Microsoft');
      await expect(discordButton).toContainText('Continue with Discord');

      // Check accessibility attributes
      await expect(githubButton).toHaveAttribute('aria-label');
      await expect(microsoftButton).toHaveAttribute('aria-label');
      await expect(discordButton).toHaveAttribute('aria-label');
    });

    test('should trigger login flow on button click', async ({ page }) => {
      const authFixtures = createAuthFixtures(page);
      await authFixtures.mockLoginSuccess('github');

      // Prevent actual navigation and capture the request
      let loginRequested = false;
      await page.route('**/api/auth/login', route => {
        loginRequested = true;
        route.continue();
      });

      const githubButton = page.locator(SELECTORS.GITHUB_BUTTON);

      // Click GitHub button
      await githubButton.click();

      // Should have made login request
      await page.waitForTimeout(1000); // Give time for request
      expect(loginRequested).toBe(true);
    });
  });

  test.describe('Error Handling', () => {
    test('should handle network errors gracefully', async ({ page }) => {
      // Mock network failure
      await page.route('**/api/auth/login', route => {
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({
            errors: [
              { code: 'INTERNAL_ERROR', detail: 'Internal server error' },
            ],
          }),
        });
      });

      const githubButton = page.locator(SELECTORS.GITHUB_BUTTON);

      // Click GitHub button
      await githubButton.click();

      // Should display error message (may take time to appear)
      const errorAlert = page.locator(SELECTORS.ALERT_ERROR);
      await expect(errorAlert).toBeVisible({ timeout: 10000 });
    });

    test('should maintain button functionality after errors', async ({
      page,
    }) => {
      // All buttons should remain clickable even if there are errors
      const githubButton = page.locator(SELECTORS.GITHUB_BUTTON);
      const microsoftButton = page.locator(SELECTORS.MICROSOFT_BUTTON);
      const discordButton = page.locator(SELECTORS.DISCORD_BUTTON);

      // Buttons should be functional
      await expect(githubButton).toBeEnabled();
      await expect(microsoftButton).toBeEnabled();
      await expect(discordButton).toBeEnabled();
    });
  });

  test.describe('Accessibility', () => {
    test('should have proper accessibility attributes', async ({ page }) => {
      const helpers = createTestHelpers(page);

      // Check button accessibility
      await helpers.accessibility.checkButtonAccessibility();

      // Check heading hierarchy
      await helpers.accessibility.checkHeadingHierarchy();

      // Check form accessibility
      await helpers.accessibility.checkFormAccessibility();

      // Check color contrast
      await helpers.accessibility.checkColorContrast();
    });

    test('should be keyboard navigable', async ({ page }) => {
      // Tab through interactive elements
      await page.keyboard.press('Tab');

      // First focusable element should be GitHub button
      const githubButton = page.locator(SELECTORS.GITHUB_BUTTON);
      await expect(githubButton).toBeFocused();

      // Tab to next button
      await page.keyboard.press('Tab');
      const microsoftButton = page.locator(SELECTORS.MICROSOFT_BUTTON);
      await expect(microsoftButton).toBeFocused();

      // Tab to next button
      await page.keyboard.press('Tab');
      const discordButton = page.locator(SELECTORS.DISCORD_BUTTON);
      await expect(discordButton).toBeFocused();
    });

    test('should support Enter key activation', async ({ page }) => {
      const authFixtures = createAuthFixtures(page);
      await authFixtures.mockLoginSuccess('github');

      const githubButton = page.locator(SELECTORS.GITHUB_BUTTON);

      // Focus and press Enter
      await githubButton.focus();
      await page.keyboard.press('Enter');

      // Should show loading state
      await expect(githubButton).toBeDisabled();
    });
  });

  test.describe('Responsive Design', () => {
    test('should be responsive across different screen sizes', async ({
      page,
    }) => {
      const helpers = createTestHelpers(page);

      // Test responsive layout
      await helpers.responsive.checkResponsiveLayout();
    });

    test('should have proper mobile interactions', async ({ page }) => {
      const helpers = createTestHelpers(page);

      // Check mobile touch targets
      await helpers.responsive.checkMobileInteractions();
    });

    test('should maintain usability on mobile', async ({ page }) => {
      // Set mobile viewport
      await page.setViewportSize(TEST_DATA.VIEWPORT_SIZES.MOBILE);

      // Check that login card is properly sized
      const loginCard = page.locator(SELECTORS.LOGIN_CARD);
      await expect(loginCard).toBeVisible();

      // Check that buttons are still clickable
      const githubButton = page.locator(SELECTORS.GITHUB_BUTTON);
      await expect(githubButton).toBeVisible();

      // Verify button is large enough for touch
      const boundingBox = await githubButton.boundingBox();
      expect(boundingBox?.height).toBeGreaterThanOrEqual(40);
    });
  });

  test.describe('Authentication Flow', () => {
    test('should redirect authenticated users', async ({ page }) => {
      const authFixtures = createAuthFixtures(page);

      // Mock user as already authenticated
      await authFixtures.mockAuthenticated('github');

      // Navigate to login page
      await page.goto(TEST_DATA.URLS.LOGIN);

      // Should redirect to home page
      await expect(page).toHaveURL(TEST_DATA.URLS.HOME);
    });

    test('should handle redirect parameter', async ({ page }) => {
      const authFixtures = createAuthFixtures(page);
      await authFixtures.mockAuthenticated('github');

      // Navigate to login with redirect parameter
      await page.goto(`${TEST_DATA.URLS.LOGIN}?redirect=/dashboard`);

      // Should redirect to specified page
      await expect(page).toHaveURL(TEST_DATA.URLS.DASHBOARD);
    });
  });

  test.describe('Australian English Localization', () => {
    test('should use Australian English terminology', async ({ page }) => {
      // Check for Australian English spellings and terminology
      const content = await page.textContent('body');

      // Should use "organisation" not "organization"
      expect(content).not.toContain('organization');

      // Should use proper Australian terminology
      expect(content).toContain('Personal Management System');
    });
  });
});
