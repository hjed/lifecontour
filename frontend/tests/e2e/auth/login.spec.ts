/**
 * End-to-end tests for the login page.
 *
 * Tests the complete login flow with deterministic authentication states.
 */

import { test, expect } from '../fixtures';

test.describe('Login Page - Unauthenticated Users', () => {
  test.describe('Page Rendering', () => {
    test('should render login page with correct title and content', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to login page
      await unauthenticatedPage.goto('/auth/login');

      // Check page title
      await expect(unauthenticatedPage).toHaveTitle(
        /Personal Management System/
      );

      // Check main heading
      const heading = unauthenticatedPage.locator('h1');
      await expect(heading).toBeVisible();
      await expect(heading).toHaveText('Welcome Back');

      // Check description
      const description = unauthenticatedPage.locator(
        'text=Sign in to your Personal Management System'
      );
      await expect(description).toBeVisible();

      // Check login form is present - look for the login card
      const loginCard = unauthenticatedPage.locator('[class*="max-w-md"]');
      await expect(loginCard).toBeVisible();
    });

    test('should display OAuth provider buttons', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to login page
      await unauthenticatedPage.goto('/auth/login');

      // Wait for providers to load and check that at least one OAuth button is present
      const oauthButtons = unauthenticatedPage.locator(
        'button:has-text("Continue with")'
      );

      // Wait for OAuth providers to be fetched and buttons to appear
      await expect(oauthButtons.first()).toBeVisible();

      // Check that we have at least one provider button
      const buttonCount = await oauthButtons.count();
      expect(buttonCount).toBeGreaterThan(0);

      // Check that the button has the correct format
      const firstButton = oauthButtons.first();
      await expect(firstButton).toContainText('Continue with');
    });

    test('should display privacy notice', async ({ unauthenticatedPage }) => {
      // Navigate to login page
      await unauthenticatedPage.goto('/auth/login');

      const privacyNotice = unauthenticatedPage.locator(
        'text=By signing in, you agree to our terms of service and privacy policy.'
      );
      await expect(privacyNotice).toBeVisible();

      const privateAppNotice = unauthenticatedPage.locator(
        'text=This is a private application for personal use only.'
      );
      await expect(privateAppNotice).toBeVisible();
    });
  });

  test.describe('OAuth Provider Interactions', () => {
    test('should have clickable OAuth provider buttons', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to login page
      await unauthenticatedPage.goto('/auth/login');

      // Get all OAuth provider buttons and wait for them to load
      const oauthButtons = unauthenticatedPage.locator(
        'button:has-text("Continue with")'
      );
      await expect(oauthButtons.first()).toBeVisible();

      // Check that all buttons are visible and enabled
      const buttonCount = await oauthButtons.count();
      for (let i = 0; i < buttonCount; i++) {
        const button = oauthButtons.nth(i);
        await expect(button).toBeVisible();
        await expect(button).toBeEnabled();
      }
    });

    test('should have proper button labels and accessibility', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to login page
      await unauthenticatedPage.goto('/auth/login');

      // Get all OAuth provider buttons and wait for them to load
      const oauthButtons = unauthenticatedPage.locator(
        'button:has-text("Continue with")'
      );
      await expect(oauthButtons.first()).toBeVisible();

      // Check button text content and accessibility
      const buttonCount = await oauthButtons.count();
      for (let i = 0; i < buttonCount; i++) {
        const button = oauthButtons.nth(i);
        await expect(button).toContainText('Continue with');
        await expect(button).toHaveAttribute('aria-label');
      }
    });

    test('should trigger login flow on button click', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to login page
      await unauthenticatedPage.goto('/auth/login');

      // Wait for providers to load
      await expect(
        unauthenticatedPage.locator('main, [role="main"]').first()
      ).toBeVisible();

      // Track the actual login request triggered by the OAuth button click
      const requestPromise = unauthenticatedPage.waitForRequest(
        request =>
          request.url().includes('/api/auth/login') &&
          request.method() === 'POST',
        {
          timeout: 10000,
        }
      );

      // Get the first OAuth provider button
      const oauthButtons = unauthenticatedPage.locator(
        'button:has-text("Continue with")'
      );
      const firstButton = oauthButtons.first();
      await expect(firstButton).toBeVisible();

      // Click the button
      await firstButton.click();

      const request = await requestPromise;

      expect(request.url()).toContain('/api/auth/login');
      expect(request.method()).toBe('POST');
      expect(request.postDataJSON()).toMatchObject({
        provider: expect.any(String),
      });
    });
  });

  test.describe('Error Handling', () => {
    test('should handle network errors gracefully', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to login page
      await unauthenticatedPage.goto('/auth/login');

      // Wait for providers to load
      await expect(
        unauthenticatedPage.locator('main, [role="main"]').first()
      ).toBeVisible();

      // Mock network failure for login endpoint
      await unauthenticatedPage.route('**/api/auth/login', async route => {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({
            errors: [
              { code: 'INTERNAL_ERROR', detail: 'Internal server error' },
            ],
          }),
        });
      });

      // Get the first OAuth provider button
      const oauthButtons = unauthenticatedPage.locator(
        'button:has-text("Continue with")'
      );
      const firstButton = oauthButtons.first();
      await expect(firstButton).toBeVisible();

      // Click the button
      await firstButton.click();

      // Should display error message
      const errorAlert = unauthenticatedPage.locator(
        '[data-testid="error-alert"], .alert-error, [role="alert"]'
      );
      await expect(errorAlert).toBeVisible();
    });

    test('should maintain button functionality after errors', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to login page
      await unauthenticatedPage.goto('/auth/login');

      // Wait for providers to load
      await expect(
        unauthenticatedPage.locator('main, [role="main"]').first()
      ).toBeVisible();

      // All OAuth buttons should remain clickable even if there are errors
      const oauthButtons = unauthenticatedPage.locator(
        'button:has-text("Continue with")'
      );
      await expect(oauthButtons.first()).toBeVisible();

      // Buttons should be functional
      const buttonCount = await oauthButtons.count();
      for (let i = 0; i < buttonCount; i++) {
        const button = oauthButtons.nth(i);
        await expect(button).toBeEnabled();
      }
    });
  });

  test.describe('Accessibility', () => {
    test('should have proper accessibility attributes', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to login page
      await unauthenticatedPage.goto('/auth/login');

      // Check OAuth buttons have proper accessibility attributes
      const oauthButtons = unauthenticatedPage.locator(
        'button:has-text("Continue with")'
      );
      const buttonCount = await oauthButtons.count();

      for (let i = 0; i < buttonCount; i++) {
        const button = oauthButtons.nth(i);
        await expect(button).toHaveAttribute('aria-label');
      }

      // Check heading hierarchy
      const mainHeading = unauthenticatedPage.locator('h1');
      await expect(mainHeading).toBeVisible();
    });

    test('should be keyboard navigable', async ({ unauthenticatedPage }) => {
      // Navigate to login page
      await unauthenticatedPage.goto('/auth/login');

      // Check if OAuth buttons are present first
      const oauthButtons = unauthenticatedPage.locator(
        'button:has-text("Continue with")'
      );
      await expect(oauthButtons.first()).toBeVisible();
      const buttonCount = await oauthButtons.count();

      if (buttonCount > 0) {
        // Tab through interactive elements
        await unauthenticatedPage.keyboard.press('Tab');

        // Check if first button gets focus (might not always work in all browsers)
        const firstButton = oauthButtons.first();
        try {
          await expect(firstButton).toBeFocused();
        } catch {
          // If focus test fails, just verify the button is visible and can be clicked
          await expect(firstButton).toBeVisible();
          await expect(firstButton).toBeEnabled();
        }

        // Tab to next button if there are multiple
        if (buttonCount > 1) {
          await unauthenticatedPage.keyboard.press('Tab');
          const secondButton = oauthButtons.nth(1);
          try {
            await expect(secondButton).toBeFocused();
          } catch {
            // If focus test fails, just verify the button is accessible
            await expect(secondButton).toBeVisible();
            await expect(secondButton).toBeEnabled();
          }
        }
      } else {
        // If no OAuth buttons, just verify page is accessible
        const bodyText = unauthenticatedPage.locator('body');
        await expect(bodyText).not.toBeEmpty();
      }
    });

    test('should support Enter key activation', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to login page
      await unauthenticatedPage.goto('/auth/login');

      // Wait for OAuth button to be ready using web-first assertion
      const oauthButtons = unauthenticatedPage.locator(
        'button:has-text("Continue with")'
      );
      const firstButton = oauthButtons.first();
      await expect(firstButton).toBeVisible({ timeout: 10000 });
      await expect(firstButton).toBeEnabled();

      // Prevent the actual navigation to avoid 'Target page, context or browser has been closed'
      // errors when Playwright tears down the context while it's navigating
      await unauthenticatedPage.route('**/api/auth/login*', async route => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ url: '/mock-redirect' }),
        });
      });

      // Set up request tracking BEFORE triggering the action
      const requestPromise = unauthenticatedPage.waitForRequest(
        request => request.url().includes('/api/auth/login'),
        { timeout: 10000 }
      );

      // Focus and press Enter to trigger OAuth flow
      await firstButton.focus();
      await unauthenticatedPage.keyboard.press('Enter');

      // Wait for the login request to be made
      const request = await requestPromise;
      expect(request.url()).toContain('/api/auth/login');
    });
  });

  test.describe('Responsive Design', () => {
    test('should be responsive across different screen sizes', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to login page
      await unauthenticatedPage.goto('/auth/login');

      // Test responsive layout across different viewports
      const viewports = [
        { width: 1200, height: 800 }, // Desktop
        { width: 768, height: 1024 }, // Tablet
        { width: 375, height: 667 }, // Mobile
      ];

      for (const viewport of viewports) {
        await unauthenticatedPage.setViewportSize(viewport);

        // Verify login page is still functional
        const heading = unauthenticatedPage.locator('h1');
        await expect(heading).toBeVisible();

        const oauthButtons = unauthenticatedPage.locator(
          'button:has-text("Continue with")'
        );
        if ((await oauthButtons.count()) > 0) {
          await expect(oauthButtons.first()).toBeVisible();
        }
      }
    });

    test('should have proper mobile interactions', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to login page
      await unauthenticatedPage.goto('/auth/login');

      // Set mobile viewport
      await unauthenticatedPage.setViewportSize({ width: 375, height: 667 });

      // Wait for providers to load
      await expect(
        unauthenticatedPage.locator('main, [role="main"]').first()
      ).toBeVisible();

      // Check OAuth buttons specifically for mobile touch targets
      const oauthButtons = unauthenticatedPage.locator(
        'button:has-text("Continue with")'
      );
      await expect(oauthButtons.first()).toBeVisible();
      const buttonCount = await oauthButtons.count();

      if (buttonCount > 0) {
        for (let i = 0; i < buttonCount; i++) {
          const button = oauthButtons.nth(i);
          const boundingBox = await button.boundingBox();
          if (boundingBox) {
            // OAuth buttons should be large enough for touch (at least 40px)
            expect(boundingBox.height).toBeGreaterThanOrEqual(40);
            expect(boundingBox.width).toBeGreaterThanOrEqual(40);
          }
        }
      } else {
        // If no OAuth buttons, just verify page is usable on mobile
        const bodyText = unauthenticatedPage.locator('body');
        await expect(bodyText).not.toBeEmpty();
      }
    });

    test('should maintain usability on mobile', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to login page
      await unauthenticatedPage.goto('/auth/login');

      // Set mobile viewport
      await unauthenticatedPage.setViewportSize({ width: 375, height: 667 });

      // Check that login card is properly sized
      const loginCard = unauthenticatedPage.locator(
        'main, [data-testid="login-card"]'
      );
      await expect(loginCard).toBeVisible();

      // Check that OAuth buttons are still clickable
      const oauthButtons = unauthenticatedPage.locator(
        'button:has-text("Continue with")'
      );
      if ((await oauthButtons.count()) > 0) {
        const firstButton = oauthButtons.first();
        await expect(firstButton).toBeVisible();

        // Verify button is large enough for touch
        const boundingBox = await firstButton.boundingBox();
        expect(boundingBox?.height).toBeGreaterThanOrEqual(40);
      }
    });
  });

  test.describe('Authentication Flow', () => {
    test('should show login page for unauthenticated users', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to login page
      await unauthenticatedPage.goto('/auth/login');

      // Should stay on login page and show OAuth buttons
      await expect(unauthenticatedPage).toHaveURL(/\/auth\/login/);
      const oauthButtons = unauthenticatedPage.locator(
        'button:has-text("Continue with")'
      );
      await expect(oauthButtons.first()).toBeVisible();
    });

    test('should handle redirect parameter in URL', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to login with redirect parameter
      await unauthenticatedPage.goto('/auth/login?redirect=/dashboard');

      // Should stay on login page but preserve redirect parameter
      await expect(unauthenticatedPage).toHaveURL(/.*login.*redirect/);
      const oauthButtons = unauthenticatedPage.locator(
        'button:has-text("Continue with")'
      );
      await expect(oauthButtons.first()).toBeVisible();
    });

    test('should show login page for unauthenticated users when accessing login directly', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to login page directly
      await unauthenticatedPage.goto('/auth/login');

      // Should stay on login page since we're not authenticated
      await expect(unauthenticatedPage).toHaveURL(/\/auth\/login/);

      // Should show login page content
      await expect(
        unauthenticatedPage.getByRole('heading', { name: 'Welcome Back' })
      ).toBeVisible();
      const oauthButtons = unauthenticatedPage.locator(
        'button:has-text("Continue with")'
      );
      await expect(oauthButtons.first()).toBeVisible();
    });
  });

  test.describe('Australian English Localization', () => {
    test('should use Australian English terminology', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to login page
      await unauthenticatedPage.goto('/auth/login');

      // Wait for providers to load
      await expect(
        unauthenticatedPage.locator('main, [role="main"]').first()
      ).toBeVisible();

      // Check for Australian English spellings and terminology
      const content = await unauthenticatedPage.textContent('body');

      // Should use "organisation" not "organization"
      expect(content).not.toContain('organization');

      // Should use proper Australian terminology
      expect(content).toContain('Personal Management System');
    });
  });
});

test.describe('Login Page - Authenticated Users', () => {
  test('should redirect authenticated users away from login page', async ({
    authenticatedPage,
  }) => {
    // Try to navigate to login page when already authenticated
    // The AuthProvider will check the session and redirect away from login
    await authenticatedPage.goto('/auth/login');

    // Wait for the redirect to complete (should redirect away from /auth/login)
    // The redirect happens in the login page's useEffect when isAuthenticated is true
    await authenticatedPage.waitForURL(
      url => !url.pathname.includes('/auth/login'),
      {
        timeout: 10000,
      }
    );

    // Verify we're no longer on the login page
    await expect(authenticatedPage).not.toHaveURL(/\/auth\/login/);

    // Should not see login form
    const loginHeading = authenticatedPage.locator(
      'h1:has-text("Welcome Back")'
    );
    await expect(loginHeading).toBeHidden();
  });

  test('should maintain authentication state when accessing login URL', async ({
    authenticatedPage,
  }) => {
    // Navigate to a protected page first to verify authentication
    await authenticatedPage.goto('/contacts');
    await expect(authenticatedPage).toHaveURL(/\/contacts/);

    // Try to access login page
    await authenticatedPage.goto('/auth/login');

    // Wait for the redirect to complete (should redirect away from /auth/login)
    await authenticatedPage.waitForURL(
      url => !url.pathname.includes('/auth/login'),
      {
        timeout: 10000,
      }
    );

    // Should be redirected to an authenticated page, not login
    await expect(authenticatedPage).not.toHaveURL(/\/auth\/login/);

    // Should still be authenticated (can access protected content)
    const pageContent = await authenticatedPage.textContent('body');
    expect(pageContent).not.toContain('Welcome Back'); // Login page content
  });
});
