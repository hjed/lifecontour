/**
 * Debug test for OAuth authentication flow.
 * This test helps debug the actual authentication flow without mocking.
 */

import { test, expect } from '@playwright/test';

test.describe('Debug OAuth Authentication', () => {
  test('should complete the full OAuth flow', async ({ page }) => {
    // Enable console logging
    page.on('console', msg => console.log('BROWSER:', msg.text()));
    page.on('pageerror', error => console.log('PAGE ERROR:', error.message));

    // Navigate to login page
    console.log('1. Navigating to login page...');
    await page.goto('/auth/login');

    // Wait for page to load
    await page.waitForLoadState('networkidle');

    // Check if login page loads
    console.log('2. Checking login page content...');
    await expect(page.locator('h1')).toContainText('Welcome Back');

    // Wait for OAuth buttons to appear
    console.log('3. Waiting for OAuth buttons...');
    const oauthButtons = page.locator('button:has-text("Continue with")');
    await expect(oauthButtons.first()).toBeVisible({ timeout: 10000 });

    // Click the OAuth button to start the flow
    console.log('4. Starting OAuth flow...');
    await oauthButtons.first().click();

    // Wait for redirect to OAuth provider login page
    console.log('5. Waiting for OAuth provider login page...');
    await page.waitForURL(/localhost:3001\/login\?login_challenge=/, { timeout: 10000 });

    // We should now be on the OAuth provider's login page
    console.log('6. On OAuth provider login page:', page.url());

    // Fill in the login form (this is the mock OAuth UI)
    console.log('7. Filling in OAuth login form...');

    // Select a test user from the dropdown
    await page.selectOption('select[name="email"]', { index: 1 }); // Select first test user

    // The password should be auto-filled by the JavaScript, but let's wait a moment
    await page.waitForTimeout(500);

    // Submit the login form
    console.log('8. Submitting OAuth login...');
    await page.click('button[type="submit"]');

    // Wait a moment and check what happens
    await page.waitForTimeout(2000);
    console.log('9. Current URL after login submission:', page.url());

    // Check if we're on a consent page
    if (page.url().includes('/consent')) {
      console.log('10. On consent page, accepting consent...');
      // Look for consent form and submit it
      const consentButton = page.locator('button[type="submit"], button:has-text("Accept"), button:has-text("Allow")');
      await expect(consentButton.first()).toBeVisible({ timeout: 5000 });
      await consentButton.first().click();
      await page.waitForTimeout(1000);
      console.log('11. Consent accepted, current URL:', page.url());
    }

    // Wait for redirect back to our application
    console.log('12. Waiting for redirect back to application...');
    await page.waitForURL(/localhost:3000/, { timeout: 15000 });

    // Check if we're redirected to the dashboard or callback page
    const finalUrl = page.url();
    console.log('13. Final URL:', finalUrl);

    if (finalUrl.includes('/auth/callback')) {
      console.log('14. On callback page, waiting for final redirect...');
      await page.waitForURL(/localhost:3000\/(?!auth)/, { timeout: 10000 });
    }

    // Verify we're logged in by checking for user-specific content
    console.log('15. Verifying login success...');
    // This will depend on your app's structure - adjust as needed
    await expect(page.locator('body')).not.toContainText('Welcome Back');

    console.log('16. OAuth flow completed successfully!');
  });
  
  test('should test direct API calls', async ({ page }) => {
    // Test the providers endpoint
    console.log('Testing /api/auth/providers...');
    const providersResponse = await page.request.get('/api/auth/providers');
    console.log('Providers status:', providersResponse.status());
    const providers = await providersResponse.json();
    console.log('Providers data:', JSON.stringify(providers, null, 2));
    
    // Test the login endpoint
    console.log('Testing /api/auth/login...');
    const loginResponse = await page.request.post('/api/auth/login', {
      data: { provider: 'generic' }
    });
    console.log('Login status:', loginResponse.status());
    
    if (loginResponse.ok()) {
      const loginData = await loginResponse.json();
      console.log('Login data:', JSON.stringify(loginData, null, 2));
    } else {
      const errorData = await loginResponse.text();
      console.log('Login error:', errorData);
    }
  });
});
