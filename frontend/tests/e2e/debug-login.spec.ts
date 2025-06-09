/**
 * Debug test to understand what's happening on the login page.
 */

import { test } from '@playwright/test';
import { setupApiMocks } from './utils/api-mocks';

test.describe('Debug Login Page', () => {
  test('debug login page elements', async ({ page }) => {
    // Set up API mocks
    await setupApiMocks(page);

    // Navigate to login page
    await page.goto('/auth/login');
    await page.waitForLoadState('networkidle');

    // Take a screenshot
    await page.screenshot({ path: 'debug-login.png', fullPage: true });

    // Check what elements are present
    console.log('=== LOGIN PAGE DEBUG ===');

    // Check if login form is visible
    const loginForm = page.locator('[data-testid="login-form"]');
    console.log('Login form visible:', await loginForm.isVisible());

    // Check for loading state
    const loadingElements = page.locator('.animate-pulse');
    console.log('Loading elements count:', await loadingElements.count());

    // Check for error messages
    const errorElements = page.locator('[data-testid="auth-error"]');
    console.log('Error elements count:', await errorElements.count());
    if ((await errorElements.count()) > 0) {
      console.log('Error message:', await errorElements.first().textContent());
    }

    // Check for provider buttons
    const providerButtons = page.locator('[data-testid^="oauth-provider-"]');
    console.log('Provider buttons count:', await providerButtons.count());

    // Check all elements with data-testid
    const allTestIds = await page.locator('[data-testid]').all();
    console.log('All elements with data-testid:');
    for (const element of allTestIds) {
      const testId = await element.getAttribute('data-testid');
      const visible = await element.isVisible();
      console.log(`  - ${testId}: ${visible ? 'visible' : 'hidden'}`);
    }

    // Check page content
    const pageContent = await page.textContent('body');
    console.log(
      'Page contains "Welcome Back":',
      pageContent?.includes('Welcome Back')
    );
    console.log('Page contains "GitHub":', pageContent?.includes('GitHub'));
    console.log(
      'Page contains "Microsoft":',
      pageContent?.includes('Microsoft')
    );

    // Wait a bit and check again
    await page.waitForTimeout(2000);

    console.log('=== AFTER 2 SECOND WAIT ===');
    console.log('Provider buttons count:', await providerButtons.count());
    console.log('Loading elements count:', await loadingElements.count());

    // Check network requests
    const requests: string[] = [];
    page.on('request', request => {
      if (request.url().includes('/api/')) {
        requests.push(request.url());
      }
    });

    // Reload to capture requests
    await page.reload();
    await page.waitForTimeout(1000);

    console.log('API requests made:', requests);
  });
});
