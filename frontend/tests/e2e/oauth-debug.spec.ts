/**
 * OAuth Debug Test
 *
 * This test helps debug the OAuth flow step by step to identify where it's failing.
 */

import { test, expect } from '@playwright/test';

test.describe('OAuth Debug', () => {
  test('should debug OAuth flow step by step', async ({ page }) => {
    console.log('🔍 [OAuth Debug] Starting OAuth flow debugging...');

    // Enable detailed logging
    page.on('console', msg => console.log('BROWSER:', msg.text()));
    page.on('pageerror', error => console.log('PAGE ERROR:', error.message));
    page.on('request', request => {
      if (request.url().includes('oauth') || request.url().includes('auth')) {
        console.log('REQUEST:', request.method(), request.url());
      }
    });
    page.on('response', response => {
      if (response.url().includes('oauth') || response.url().includes('auth')) {
        console.log('RESPONSE:', response.status(), response.url());
      }
    });

    // Step 1: Check if OAuth provider is accessible
    console.log('🔍 [Step 1] Checking OAuth provider accessibility...');

    try {
      const hydraResponse = await page.request.get(
        'http://localhost:4446/.well-known/openid_configuration'
      );
      console.log('Hydra public endpoint status:', hydraResponse.status());

      if (hydraResponse.ok()) {
        const config = await hydraResponse.json();
        console.log('OAuth provider config:', {
          issuer: config.issuer,
          authorization_endpoint: config.authorization_endpoint,
          token_endpoint: config.token_endpoint,
        });
      }
    } catch (error) {
      console.log('❌ OAuth provider not accessible:', error);
    }

    // Step 2: Check if backend is accessible
    console.log('🔍 [Step 2] Checking backend accessibility...');

    try {
      const backendResponse = await page.request.get(
        'http://localhost:8001/api/health'
      );
      console.log('Backend health status:', backendResponse.status());
    } catch (error) {
      console.log('❌ Backend not accessible:', error);
    }

    // Step 3: Navigate to login page
    console.log('🔍 [Step 3] Navigating to login page...');

    await page.goto('http://localhost:3000/auth/login');
    await page.waitForLoadState('networkidle');

    const loginUrl = page.url();
    console.log('Login page URL:', loginUrl);

    // Step 4: Check for OAuth buttons
    console.log('🔍 [Step 4] Checking for OAuth buttons...');

    const oauthButtons = page.locator('button:has-text("Continue with")');
    const buttonCount = await oauthButtons.count();
    console.log('OAuth buttons found:', buttonCount);

    if (buttonCount === 0) {
      console.log('❌ No OAuth buttons found - checking page content...');
      const pageContent = await page.textContent('body');
      console.log('Page content preview:', pageContent?.substring(0, 500));
      return;
    }

    // Step 5: Click OAuth button and track the flow
    console.log('🔍 [Step 5] Clicking OAuth button and tracking flow...');

    const button = oauthButtons.first();
    await button.waitFor({ timeout: 5000 });

    // Track navigation
    let navigationCount = 0;
    page.on('framenavigated', frame => {
      if (frame === page.mainFrame()) {
        navigationCount++;
        console.log(`Navigation ${navigationCount}:`, frame.url());
      }
    });

    // Click button
    await button.click();

    // Wait for navigation or timeout
    try {
      await page.waitForNavigation({ timeout: 10000 });
      console.log('Navigation completed to:', page.url());
    } catch (error) {
      console.log('Navigation timeout - current URL:', page.url());
    }

    // Step 6: Check current state
    console.log('🔍 [Step 6] Checking current state...');

    const currentUrl = page.url();
    console.log('Current URL:', currentUrl);

    if (currentUrl.includes('localhost:4446')) {
      console.log('✅ Successfully redirected to OAuth provider');

      // Wait a bit for any automatic redirects
      await page.waitForTimeout(5000);

      const finalUrl = page.url();
      console.log('Final URL after waiting:', finalUrl);

      if (finalUrl.includes('/auth/callback')) {
        console.log('✅ OAuth flow completed - reached callback');
      } else if (finalUrl.includes('/auth/login')) {
        console.log('❌ Redirected back to login - OAuth failed');
      } else {
        console.log('❓ Unexpected final URL');
      }
    } else if (currentUrl.includes('/auth/login')) {
      console.log('❌ Still on login page - OAuth button click failed');
    } else {
      console.log('❓ Unexpected redirect to:', currentUrl);
    }

    // Step 7: Check session state (using correct endpoint)
    console.log('🔍 [Step 7] Checking session state...');

    try {
      const sessionResponse = await page.request.get('/api/auth/status');
      console.log('Session check status:', sessionResponse.status());

      if (sessionResponse.ok()) {
        const sessionData = await sessionResponse.json();
        console.log('Session data:', sessionData);

        if (sessionData.authenticated) {
          console.log('✅ Session created successfully!');
          console.log('User:', sessionData.user?.email);
        } else {
          console.log('❌ Session not authenticated');
        }
      } else {
        const errorText = await sessionResponse.text();
        console.log('Session error:', errorText);
      }
    } catch (error) {
      console.log('Session check failed:', error);
    }

    // Step 8: Wait a bit and check again to see if it's a timing issue
    console.log('🔍 [Step 8] Waiting and checking session again...');
    await page.waitForTimeout(2000);

    try {
      const sessionResponse2 = await page.request.get('/api/auth/status');
      console.log('Second session check status:', sessionResponse2.status());

      if (sessionResponse2.ok()) {
        const sessionData2 = await sessionResponse2.json();
        console.log('Second session data:', sessionData2);

        if (sessionData2.authenticated) {
          console.log('✅ Session working after delay!');
        } else {
          console.log('❌ Session still not authenticated after delay');
        }
      }
    } catch (error) {
      console.log('Second session check failed:', error);
    }

    console.log('🔍 [OAuth Debug] Debugging complete');
  });

  test('should test OAuth provider endpoints directly', async ({ page }) => {
    console.log('🔍 [OAuth Provider Test] Testing OAuth provider endpoints...');

    // Test Hydra public endpoint
    try {
      const publicResponse = await page.request.get(
        'http://localhost:4446/.well-known/openid_configuration'
      );
      console.log('Public endpoint status:', publicResponse.status());

      if (publicResponse.ok()) {
        const config = await publicResponse.json();
        console.log(
          'OAuth configuration valid:',
          !!config.authorization_endpoint
        );
      }
    } catch (error) {
      console.log('❌ Public endpoint failed:', error);
    }

    // Test Hydra admin endpoint
    try {
      const adminResponse = await page.request.get(
        'http://localhost:4447/admin/clients/test-client-id'
      );
      console.log('Admin endpoint status:', adminResponse.status());

      if (adminResponse.ok()) {
        const client = await adminResponse.json();
        console.log('OAuth client found:', client.client_id);
      }
    } catch (error) {
      console.log('❌ Admin endpoint failed:', error);
    }

    // Test login/consent service
    try {
      const consentResponse = await page.request.get(
        'http://localhost:3002/health'
      );
      console.log('Consent service status:', consentResponse.status());
    } catch (error) {
      console.log('❌ Consent service failed:', error);
    }
  });
});
