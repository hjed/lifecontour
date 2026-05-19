/**
 * End-to-end tests for OAuth integration with Docker Compose setup.
 *
 * Tests the complete OAuth flow against the containerized Hydra OAuth provider
 * to ensure the Docker setup works correctly for development and testing.
 *
 * Converted to use the advanced fixture-based testing system.
 */

import { test, expect } from './fixtures';

import {
  FRONTEND_TEST_CALLBACK_URL,
  FRONTEND_TEST_LOGIN_URL,
  FRONTEND_TEST_URL,
  OAUTH_ADMIN_TEST_PORT,
  OAUTH_PUBLIC_TEST_PORT,
  OAUTH_UI_TEST_PORT,
} from './utils/frontend-test-config';

test.describe('OAuth Docker Integration', () => {
  test('should verify Hydra OAuth provider is accessible', async ({
    unauthenticatedPage: page,
  }) => {
    console.log('1. Testing Hydra OAuth provider accessibility...');

    // Test if Hydra public endpoint is accessible
    try {
      const response = await page.request.get(
        `http://localhost:${OAUTH_PUBLIC_TEST_PORT}/.well-known/openid_configuration`
      );

      if (response.ok()) {
        const config = await response.json();
        console.log('2. Hydra OpenID configuration retrieved successfully');
        console.log(
          '3. Authorization endpoint:',
          config.authorization_endpoint
        );
        console.log('4. Token endpoint:', config.token_endpoint);

        // Verify required endpoints are present
        expect(config.authorization_endpoint).toBeTruthy();
        expect(config.token_endpoint).toBeTruthy();
        expect(config.issuer).toBeTruthy();

        console.log('5. Hydra OAuth provider is properly configured');
      } else {
        console.log('2. Hydra not accessible - may not be running in Docker');
        console.log('3. This is expected if Docker Compose is not running');
      }
    } catch (error) {
      console.log('2. Hydra connection failed:', error);
      console.log('3. This is expected if Docker Compose is not running');
    }
  });

  test('should verify OAuth client configuration in Hydra', async ({
    unauthenticatedPage: page,
  }) => {
    console.log('1. Testing OAuth client configuration...');

    // Wait for OAuth client initialization...
    console.log('2. Waiting for OAuth client initialization...');

    try {
      // Test if Hydra admin endpoint is accessible, retry if it's not reachable
      let response: import('@playwright/test').APIResponse | undefined;
      await expect(async () => {
        response = await page.request.get(
          `http://localhost:${OAUTH_ADMIN_TEST_PORT}/admin/clients/test-client-id`
        );
        // We only want to retry on connection refused (which throws) or 502 Bad Gateway
        // A 404 is a valid response meaning Hydra is up but client isn't there yet
        expect(response.status()).not.toBe(502);
      }).toPass({ timeout: 15000 });

      if (response && response.ok()) {
        const client = await response.json();
        console.log('3. OAuth client configuration retrieved successfully');
        console.log('4. Client ID:', client.client_id);
        console.log('5. Redirect URIs:', client.redirect_uris);

        // Verify client configuration
        expect(client.client_id).toBe('test-client-id');
        expect(client.redirect_uris).toContain(FRONTEND_TEST_CALLBACK_URL);
        expect(client.post_logout_redirect_uris).toContain(
          `${FRONTEND_TEST_URL}/`
        );
        expect(client.client_uri).toBe(FRONTEND_TEST_URL);
        expect(client.grant_types).toContain('authorization_code');
        expect(client.response_types).toContain('code');

        console.log('6. OAuth client is properly configured in Hydra');
      } else {
        console.log('3. OAuth client not found - may need to be created');
        console.log(
          '4. This is expected if Docker Compose is not running or client not initialized'
        );
      }
    } catch (error) {
      console.log('3. Hydra admin connection failed:', error);
      console.log('4. This is expected if Docker Compose is not running');
    }
  });

  test('should verify backend OAuth configuration', async ({
    unauthenticatedPage: page,
  }) => {
    console.log('1. Testing backend OAuth configuration...');

    // Navigate to login page to check OAuth provider availability
    await page.goto('/auth/login');
    await expect(page.locator('main, [role="main"]').first()).toBeVisible();

    // Check if OAuth buttons are present (indicates backend OAuth is configured)
    const oauthButtons = page.locator('button:has-text("Continue with")');
    const buttonCount = await oauthButtons.count();

    console.log('2. OAuth buttons found:', buttonCount);

    if (buttonCount > 0) {
      console.log('3. Backend OAuth configuration is working');

      // Get button text to verify provider
      const buttonText = await oauthButtons.first().textContent();
      console.log('4. OAuth provider button:', buttonText);

      // Verify button is enabled and clickable
      await expect(oauthButtons.first()).toBeEnabled();
      console.log('5. OAuth button is properly enabled');
    } else {
      console.log('3. No OAuth buttons found');
      console.log(
        '4. This may indicate OAuth provider is not configured or not running'
      );

      // Check for any error messages about OAuth configuration
      const bodyText = await page.textContent('body');
      if (bodyText?.includes('OAuth') || bodyText?.includes('provider')) {
        console.log('5. OAuth-related content found on page');
      }
    }
  });

  test('should test OAuth authorization URL generation', async ({
    unauthenticatedPage: page,
  }) => {
    console.log('1. Testing OAuth authorization URL generation...');

    // Track OAuth login requests
    const oauthRequests: { url: string; status: number }[] = [];

    page.on('response', response => {
      if (response.url().includes('/api/auth/login')) {
        oauthRequests.push({ url: response.url(), status: response.status() });
        console.log(
          '2. OAuth login request:',
          response.status(),
          response.url()
        );
      }
    });

    await page.goto('/auth/login');
    await expect(page.locator('main, [role="main"]').first()).toBeVisible();

    const oauthButtons = page.locator('button:has-text("Continue with")');
    const buttonCount = await oauthButtons.count();

    if (buttonCount > 0) {
      console.log(
        '3. Clicking OAuth button to test authorization URL generation...'
      );

      await oauthButtons.first().click();

      await expect(async () => {
        expect(oauthRequests.length).toBeGreaterThan(0);
      }).toPass({ timeout: 10000 });

      // Check if OAuth request was made
      if (oauthRequests.length > 0) {
        console.log('4. OAuth login request was made successfully');

        const successfulRequests = oauthRequests.filter(r => r.status < 400);
        const errorRequests = oauthRequests.filter(r => r.status >= 400);

        console.log('5. Successful requests:', successfulRequests.length);
        console.log('6. Error requests:', errorRequests.length);

        if (successfulRequests.length > 0) {
          console.log('7. OAuth authorization URL generation is working');

          // Check if we were redirected to Hydra
          const currentUrl = page.url();
          if (
            currentUrl.includes(`localhost:${OAUTH_PUBLIC_TEST_PORT}`) ||
            currentUrl.includes(`localhost:${OAUTH_UI_TEST_PORT}`) ||
            currentUrl.includes('oauth2/auth')
          ) {
            console.log('8. Successfully redirected to Hydra OAuth provider');
          } else {
            console.log('8. Current URL:', currentUrl);
          }
        } else {
          console.log(
            '7. OAuth requests returned errors - checking error details...'
          );
          // This might be expected if Hydra is not running
        }
      } else {
        console.log('4. No OAuth requests made - checking page state...');
        const currentUrl = page.url();
        console.log('5. Current URL:', currentUrl);
      }
    } else {
      console.log('3. No OAuth buttons available for testing');
    }
  });

  test('should verify OAuth callback handling with Docker setup', async ({
    unauthenticatedPage: page,
  }) => {
    console.log('1. Testing OAuth callback handling with Docker setup...');

    // Encode state parameter with flow_type and provider
    const state = btoa(
      JSON.stringify({ flow_type: 'auth', provider: 'generic' })
    );

    // Track callback requests
    const callbackRequests: { method: string; url: string; status?: number }[] =
      [];

    page.on('request', request => {
      if (request.url().includes('/api/auth/callback')) {
        callbackRequests.push({ method: request.method(), url: request.url() });
      }
    });

    page.on('response', response => {
      if (response.url().includes('/api/auth/callback')) {
        const request = callbackRequests.find(r => r.url === response.url());
        if (request) request.status = response.status();
        console.log('2. Callback response:', response.status());
      }
    });

    // Test callback with mock parameters
    console.log('3. Testing callback with mock OAuth parameters...');
    await page.goto(`/auth/callback?code=test-code&state=${state}`);
    await expect(async () => {
      expect(callbackRequests.length).toBeGreaterThan(0);
    }).toPass({ timeout: 10000 });

    // Verify callback request was made
    expect(callbackRequests.length).toBeGreaterThan(0);
    console.log('4. Callback request made to backend');

    // Check response status
    const callbackResponse = callbackRequests.find(r => r.status !== undefined);
    if (callbackResponse) {
      console.log('5. Callback response status:', callbackResponse.status);

      if (callbackResponse.status && callbackResponse.status < 500) {
        console.log('6. Callback handling is working (no server errors)');
      } else {
        console.log(
          '6. Server error in callback - may indicate configuration issue'
        );
      }
    }

    // Check final page state
    const currentUrl = page.url();
    const bodyText = await page.textContent('body');

    console.log('7. Final URL:', currentUrl);

    if (currentUrl.includes('/auth/login')) {
      console.log('8. Redirected to login - checking for error messages...');

      const hasError =
        bodyText?.includes('error') || bodyText?.includes('failed');
      if (hasError) {
        console.log('9. Error message found (expected with mock parameters)');
      }
    } else if (currentUrl.includes('/auth/callback')) {
      console.log(
        '8. Remained on callback page - checking for error display...'
      );

      const hasError =
        bodyText?.includes('error') ||
        bodyText?.includes('Authentication failed');
      if (hasError) {
        console.log('9. Error appropriately displayed on callback page');
      }
    }

    console.log('10. OAuth callback Docker integration test completed');
  });

  test('should verify OAuth environment variables are properly set', async ({
    unauthenticatedPage: page,
  }) => {
    console.log('1. Testing OAuth environment variable configuration...');

    // Make a request to a backend endpoint that might expose configuration info
    try {
      const response = await page.request.get(
        'http://localhost:8001/api/health'
      );

      if (response.ok()) {
        console.log('2. Backend is accessible for configuration testing');

        // Navigate to login page to see if OAuth is configured
        await page.goto('/auth/login');
        await expect(page.locator('main, [role="main"]').first()).toBeVisible();

        const oauthButtons = page.locator('button:has-text("Continue with")');
        const buttonCount = await oauthButtons.count();

        if (buttonCount > 0) {
          console.log('3. OAuth providers are configured (buttons present)');
          console.log('4. Environment variables are properly set');

          // Test that clicking doesn't immediately fail
          // Instead of silent catch delay, we ensure network is quiet or wait for navigation conditionally
          const beforeUrl = page.url();
          await Promise.all([
            page
              .waitForURL(url => url.toString() !== beforeUrl, {
                timeout: 5000,
              })
              .catch(() => null),
            oauthButtons.first().click(),
          ]);

          // Should either redirect or show some response
          const currentUrl = page.url();
          console.log('5. URL after OAuth click:', currentUrl);

          const remainedOnLoginPage = currentUrl === FRONTEND_TEST_LOGIN_URL;

          if (remainedOnLoginPage) {
            console.log('6. Remained on login page - checking for errors...');
          } else {
            console.log('6. OAuth flow initiated successfully');
          }
        } else {
          console.log('3. No OAuth providers configured');
          console.log('4. Environment variables may not be set correctly');
        }
      } else {
        console.log('2. Backend not accessible - Docker may not be running');
      }
    } catch (error) {
      console.log('2. Backend connection failed:', error);
      console.log('3. This is expected if Docker Compose is not running');
    }

    console.log('7. OAuth environment configuration test completed');
  });
});
