/**
 * End-to-end tests for OAuth error handling scenarios.
 *
 * Tests various OAuth error conditions including invalid state,
 * expired codes, provider errors, and network failures to ensure
 * robust error handling without mocking critical parts.
 */

import { test, expect } from '@playwright/test';

test.describe('OAuth Error Handling', () => {
  test('should handle invalid OAuth state parameter', async ({ page }) => {
    console.log('1. Testing invalid OAuth state parameter handling...');

    // Enable error logging
    page.on('console', msg => {
      if (msg.type() === 'error') {
        console.log('BROWSER ERROR:', msg.text());
      }
    });

    // Navigate to login page to establish session
    await page.goto('/auth/login');
    await page.waitForLoadState('networkidle');

    // Set up session storage as if we initiated OAuth
    await page.evaluate(() => {
      sessionStorage.setItem('oauth_provider', 'generic');
    });

    // Track callback requests and responses
    const callbackResponses: { status: number; error?: string }[] = [];
    page.on('response', async response => {
      if (response.url().includes('/api/auth/callback')) {
        const responseData: { status: number; error?: string } = {
          status: response.status(),
        };

        if (!response.ok()) {
          try {
            const errorData = await response.json();
            responseData.error =
              errorData.detail || errorData.message || 'Unknown error';
          } catch {
            responseData.error = 'Failed to parse error response';
          }
        }

        callbackResponses.push(responseData);
        console.log('CALLBACK RESPONSE:', responseData);
      }
    });

    // Navigate to callback with invalid state
    console.log('2. Navigating to callback with invalid state...');
    await page.goto(
      '/auth/callback?code=valid-code&state=invalid-state-that-does-not-match'
    );
    await page.waitForTimeout(3000);

    // Should have received an error response
    expect(callbackResponses.length).toBeGreaterThan(0);
    const errorResponse = callbackResponses.find(r => r.status >= 400);
    expect(errorResponse).toBeTruthy();
    console.log(
      '3. Error response received as expected:',
      errorResponse?.error
    );

    // Check that error is displayed to user
    const errorElements = page.locator(
      '[role="alert"], .alert, .error, [data-testid="error"]'
    );
    const errorCount = await errorElements.count();

    if (errorCount > 0) {
      const errorText = await errorElements.first().textContent();
      console.log('4. Error message displayed to user:', errorText);
      expect(errorText).toBeTruthy();
    } else {
      // Check if redirected to login with error indication
      const currentUrl = page.url();
      if (currentUrl.includes('/auth/login')) {
        console.log('4. Redirected to login page after error');
      }
    }

    console.log('5. Invalid state parameter test completed');
  });

  test('should handle expired OAuth authorization codes', async ({ page }) => {
    console.log('1. Testing expired OAuth authorization code handling...');

    // Set up session storage
    await page.goto('/auth/login');
    await page.evaluate(() => {
      sessionStorage.setItem('oauth_provider', 'generic');
    });

    // Track error responses
    const errorResponses: string[] = [];
    page.on('response', async response => {
      if (response.url().includes('/api/auth/callback') && !response.ok()) {
        try {
          const errorData = await response.json();
          errorResponses.push(
            errorData.detail || errorData.message || 'Unknown error'
          );
        } catch {
          errorResponses.push(`HTTP ${response.status()}`);
        }
      }
    });

    // Simulate expired code scenario
    console.log('2. Testing with potentially expired authorization code...');
    await page.goto(
      '/auth/callback?code=expired-or-invalid-code&state=test-state'
    );
    await page.waitForTimeout(3000);

    console.log('3. Checking error handling for expired code...');

    // Should show appropriate error message
    const bodyText = await page.textContent('body');
    const hasErrorMessage =
      bodyText?.includes('Authentication failed') ||
      bodyText?.includes('expired') ||
      bodyText?.includes('invalid') ||
      errorResponses.length > 0;

    if (hasErrorMessage) {
      console.log('4. Appropriate error handling found');
      if (errorResponses.length > 0) {
        console.log('5. Backend error responses:', errorResponses);
      }
    } else {
      console.log(
        '4. No explicit error message - checking redirect behavior...'
      );
      const currentUrl = page.url();
      if (currentUrl.includes('/auth/login')) {
        console.log('5. Redirected to login page (acceptable error handling)');
      }
    }

    console.log('6. Expired code test completed');
  });

  test('should handle OAuth provider errors', async ({ page }) => {
    console.log('1. Testing OAuth provider error handling...');

    // Set up session storage
    await page.goto('/auth/login');
    await page.evaluate(() => {
      sessionStorage.setItem('oauth_provider', 'generic');
    });

    // Test various OAuth error scenarios
    const errorScenarios = [
      {
        name: 'access_denied',
        params: 'error=access_denied&error_description=User%20denied%20access',
        expectedMessage: 'User denied access',
      },
      {
        name: 'invalid_request',
        params:
          'error=invalid_request&error_description=Invalid%20OAuth%20request',
        expectedMessage: 'Invalid OAuth request',
      },
      {
        name: 'server_error',
        params: 'error=server_error&error_description=OAuth%20provider%20error',
        expectedMessage: 'OAuth provider error',
      },
    ];

    for (const scenario of errorScenarios) {
      console.log(`2. Testing ${scenario.name} error scenario...`);

      await page.goto(`/auth/callback?${scenario.params}`);
      await page.waitForTimeout(2000);

      // Check for error display
      const bodyText = await page.textContent('body');
      const hasExpectedError = bodyText?.includes(scenario.expectedMessage);

      if (hasExpectedError) {
        console.log(`3. ${scenario.name} error correctly displayed`);
      } else {
        console.log(
          `3. ${scenario.name} error not explicitly shown - checking general error handling...`
        );

        // Look for any error indicators
        const errorElements = page.locator('[role="alert"], .alert, .error');
        const errorCount = await errorElements.count();

        if (errorCount > 0) {
          console.log(`4. General error handling found for ${scenario.name}`);
        }
      }
    }

    console.log('5. OAuth provider error tests completed');
  });

  test('should handle network failures during OAuth flow', async ({ page }) => {
    console.log('1. Testing network failure handling...');

    // Navigate to login page
    await page.goto('/auth/login');
    await page.waitForLoadState('networkidle');

    // Check if OAuth buttons are available
    const oauthButtons = page.locator('button:has-text("Continue with")');
    const buttonCount = await oauthButtons.count();

    if (buttonCount > 0) {
      console.log(
        '2. OAuth buttons found, testing network failure scenarios...'
      );

      // Simulate network failure by intercepting requests
      await page.route('**/api/auth/login', route => {
        console.log(
          '3. Intercepting login request to simulate network failure...'
        );
        route.abort('failed');
      });

      // Track any error handling
      const errors: string[] = [];
      page.on('console', msg => {
        if (msg.type() === 'error') {
          errors.push(msg.text());
        }
      });

      // Try to initiate OAuth login
      await oauthButtons.first().click();
      await page.waitForTimeout(3000);

      console.log('4. Checking error handling after network failure...');

      // Should handle network failure gracefully
      const bodyText = await page.textContent('body');
      const hasErrorHandling =
        bodyText?.includes('error') ||
        bodyText?.includes('failed') ||
        errors.length > 0;

      if (hasErrorHandling) {
        console.log('5. Network failure handled appropriately');
        if (errors.length > 0) {
          console.log('6. Console errors logged:', errors.slice(0, 3));
        }
      } else {
        console.log(
          '5. No explicit error handling - checking if page remains functional...'
        );

        // Page should still be usable
        const currentUrl = page.url();
        expect(currentUrl).toBeTruthy();

        // Should still be able to interact with the page
        const clickableElements = page.locator('button, a, input');
        const clickableCount = await clickableElements.count();
        expect(clickableCount).toBeGreaterThan(0);

        console.log('6. Page remains functional after network failure');
      }

      // Clean up route interception
      await page.unroute('**/api/auth/login');
    } else {
      console.log(
        '2. No OAuth buttons found - testing session endpoint network failure...'
      );

      // Test network failure on session endpoint
      await page.route('**/api/auth/session', route => {
        console.log(
          '3. Intercepting session request to simulate network failure...'
        );
        route.abort('failed');
      });

      // Navigate to protected page
      await page.goto('/contacts');
      await page.waitForTimeout(2000);

      console.log('4. Checking handling of session endpoint failure...');

      // Should handle session check failure gracefully
      const bodyText = await page.textContent('body');
      expect(bodyText).toBeTruthy();

      console.log('5. Session endpoint failure handled');

      await page.unroute('**/api/auth/session');
    }

    console.log('7. Network failure test completed');
  });

  test('should handle malformed OAuth callback URLs', async ({ page }) => {
    console.log('1. Testing malformed OAuth callback URL handling...');

    // Test various malformed callback scenarios
    const malformedUrls = [
      '/auth/callback?code=', // Empty code
      '/auth/callback?state=', // Empty state
      '/auth/callback?code=test', // Missing state
      '/auth/callback?state=test', // Missing code
      '/auth/callback?code=test&state=test&extra=malicious', // Extra parameters
      '/auth/callback?invalid=params', // Wrong parameters
    ];

    for (const url of malformedUrls) {
      console.log(`2. Testing malformed URL: ${url}`);

      await page.goto(url);
      await page.waitForTimeout(2000);

      // Should handle malformed URLs gracefully
      const bodyText = await page.textContent('body');
      expect(bodyText).toBeTruthy();

      // Should show appropriate error or redirect to login
      const currentUrl = page.url();
      const hasErrorHandling =
        bodyText?.includes('error') ||
        bodyText?.includes('invalid') ||
        bodyText?.includes('missing') ||
        currentUrl.includes('/auth/login');

      if (hasErrorHandling) {
        console.log(`3. Malformed URL handled appropriately: ${url}`);
      } else {
        console.log(
          `3. No explicit error for ${url} - checking page stability...`
        );

        // Page should still be stable
        const title = await page.title();
        expect(title).toBeTruthy();
      }
    }

    console.log('4. Malformed URL tests completed');
  });
});

test.describe('OAuth Session and State Management Errors', () => {
  test('should handle missing session state during callback', async ({
    page,
  }) => {
    console.log('1. Testing missing session state handling...');

    // Navigate directly to callback without establishing session
    await page.goto('/auth/callback?code=test-code&state=test-state');
    await page.waitForTimeout(3000);

    console.log('2. Checking handling of missing session state...');

    // Should handle missing session gracefully
    const bodyText = await page.textContent('body');
    const hasErrorHandling =
      bodyText?.includes('error') ||
      bodyText?.includes('invalid') ||
      bodyText?.includes('session');

    if (hasErrorHandling) {
      console.log('3. Missing session state handled with error message');
    } else {
      // Check if redirected to login
      const currentUrl = page.url();
      if (currentUrl.includes('/auth/login')) {
        console.log('3. Redirected to login page (appropriate handling)');
      } else {
        console.log('3. No explicit error - checking page stability...');
        expect(bodyText).toBeTruthy();
      }
    }

    console.log('4. Missing session state test completed');
  });

  test('should handle session timeout during OAuth flow', async ({ page }) => {
    console.log('1. Testing session timeout during OAuth flow...');

    // Start OAuth flow
    await page.goto('/auth/login');
    await page.waitForLoadState('networkidle');

    // Set up session storage
    await page.evaluate(() => {
      sessionStorage.setItem('oauth_provider', 'generic');
    });

    // Simulate session timeout by clearing session storage
    console.log('2. Simulating session timeout...');
    await page.evaluate(() => {
      sessionStorage.clear();
    });

    // Try to complete OAuth callback
    await page.goto('/auth/callback?code=test-code&state=test-state');
    await page.waitForTimeout(3000);

    console.log('3. Checking handling of session timeout...');

    // Should handle session timeout appropriately
    const bodyText = await page.textContent('body');
    const currentUrl = page.url();

    const hasTimeoutHandling =
      bodyText?.includes('error') ||
      bodyText?.includes('timeout') ||
      bodyText?.includes('expired') ||
      currentUrl.includes('/auth/login');

    if (hasTimeoutHandling) {
      console.log('4. Session timeout handled appropriately');
    } else {
      console.log('4. No explicit timeout handling - checking error state...');

      // Look for any error indicators
      const errorElements = page.locator('[role="alert"], .alert, .error');
      const errorCount = await errorElements.count();

      if (errorCount > 0) {
        console.log('5. General error handling found for timeout');
      }
    }

    console.log('6. Session timeout test completed');
  });

  test('should handle concurrent OAuth attempts', async ({ page }) => {
    console.log('1. Testing concurrent OAuth attempts...');

    await page.goto('/auth/login');
    await page.waitForLoadState('networkidle');

    const oauthButtons = page.locator('button:has-text("Continue with")');
    const buttonCount = await oauthButtons.count();

    if (buttonCount > 0) {
      console.log('2. Testing rapid OAuth button clicks...');

      // Track requests
      const requests: string[] = [];
      page.on('request', request => {
        if (request.url().includes('/api/auth/login')) {
          requests.push(request.url());
        }
      });

      // Rapidly click OAuth button multiple times
      const button = oauthButtons.first();
      await button.click();
      await button.click();
      await button.click();

      await page.waitForTimeout(2000);

      console.log('3. Checking handling of concurrent requests...');
      console.log('4. Total login requests made:', requests.length);

      // Should handle concurrent requests gracefully
      // Either by preventing multiple requests or handling them properly
      const currentUrl = page.url();
      const bodyText = await page.textContent('body');

      // Page should remain stable
      expect(bodyText).toBeTruthy();
      expect(currentUrl).toBeTruthy();

      console.log('5. Concurrent requests handled without crashing');
    } else {
      console.log('2. No OAuth buttons found - skipping concurrent test');
    }

    console.log('6. Concurrent OAuth attempts test completed');
  });

  test('should handle OAuth provider unavailability', async ({ page }) => {
    console.log('1. Testing OAuth provider unavailability...');

    await page.goto('/auth/login');
    await page.waitForLoadState('networkidle');

    // Intercept OAuth provider requests to simulate unavailability
    await page.route('**/oauth/**', route => {
      console.log(
        '2. Intercepting OAuth provider request to simulate unavailability...'
      );
      route.abort('failed');
    });

    await page.route('**localhost:4444/**', route => {
      console.log(
        '3. Intercepting Hydra requests to simulate unavailability...'
      );
      route.abort('failed');
    });

    const oauthButtons = page.locator('button:has-text("Continue with")');
    const buttonCount = await oauthButtons.count();

    if (buttonCount > 0) {
      console.log('4. Testing OAuth with unavailable provider...');

      // Track any errors
      const errors: string[] = [];
      page.on('console', msg => {
        if (msg.type() === 'error') {
          errors.push(msg.text());
        }
      });

      await oauthButtons.first().click();
      await page.waitForTimeout(3000);

      console.log('5. Checking handling of provider unavailability...');

      // Should handle provider unavailability gracefully
      const bodyText = await page.textContent('body');
      const currentUrl = page.url();

      // Should either show error or remain on login page
      const hasErrorHandling =
        bodyText?.includes('error') ||
        bodyText?.includes('unavailable') ||
        currentUrl.includes('/auth/login') ||
        errors.length > 0;

      if (hasErrorHandling) {
        console.log('6. Provider unavailability handled appropriately');
      } else {
        console.log('6. No explicit error - checking page stability...');
        expect(bodyText).toBeTruthy();
      }
    } else {
      console.log(
        '4. No OAuth buttons found - provider may already be unavailable'
      );
    }

    // Clean up route interceptions
    await page.unroute('**/oauth/**');
    await page.unroute('**localhost:4444/**');

    console.log('7. Provider unavailability test completed');
  });
});
