/**
 * Infrastructure smoke tests for the containerized Hydra OAuth provider.
 *
 * These verify that the Docker Compose OAuth setup is correctly configured:
 * the Hydra OIDC discovery document is served and the test OAuth client is
 * registered with the expected redirect URIs and grant/response types.
 *
 * The user-facing OAuth flow itself is covered by oauth-flow.spec.ts (happy
 * path) and oauth-error-handling.spec.ts (error/edge cases).
 */

import { test, expect } from './fixtures';

import {
  FRONTEND_TEST_CALLBACK_URL,
  FRONTEND_TEST_URL,
  OAUTH_ADMIN_TEST_PORT,
  OAUTH_PUBLIC_TEST_PORT,
} from './utils/frontend-test-config';

test.describe('OAuth Docker Integration', () => {
  test('Hydra serves a valid OpenID configuration', async ({
    unauthenticatedPage: page,
  }) => {
    const response = await page.request.get(
      `http://localhost:${OAUTH_PUBLIC_TEST_PORT}/.well-known/openid-configuration`
    );
    expect(response.ok()).toBe(true);

    const config = await response.json();
    expect(config.authorization_endpoint).toBeTruthy();
    expect(config.token_endpoint).toBeTruthy();
    expect(config.issuer).toBeTruthy();
  });

  test('Hydra has the test OAuth client registered correctly', async ({
    unauthenticatedPage: page,
  }) => {
    // Retry until Hydra admin is reachable and the client has been created
    // (Hydra may still be initializing immediately after container start).
    let response: import('@playwright/test').APIResponse | undefined;
    await expect(async () => {
      response = await page.request.get(
        `http://localhost:${OAUTH_ADMIN_TEST_PORT}/admin/clients/test-client-id`
      );
      expect(response.ok()).toBe(true);
    }).toPass({ timeout: 15000 });

    const client = await response!.json();
    expect(client.client_id).toBe('test-client-id');
    expect(client.redirect_uris).toContain(FRONTEND_TEST_CALLBACK_URL);
    expect(client.post_logout_redirect_uris).toContain(`${FRONTEND_TEST_URL}/`);
    expect(client.client_uri).toBe(FRONTEND_TEST_URL);
    expect(client.grant_types).toContain('authorization_code');
    expect(client.response_types).toContain('code');
  });
});
