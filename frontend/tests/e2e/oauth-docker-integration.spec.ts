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
  MCP_TEST_CALLBACK_URL,
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
    // FastMCP's OAuth proxy serves its own callback under the MCP mount path.
    // Without it registered, Hydra rejects the MCP flow at the authorize step.
    expect(client.redirect_uris).toContain(MCP_TEST_CALLBACK_URL);
    expect(client.post_logout_redirect_uris).toContain(`${FRONTEND_TEST_URL}/`);
    expect(client.client_uri).toBe(FRONTEND_TEST_URL);
    expect(client.grant_types).toContain('authorization_code');
    expect(client.response_types).toContain('code');
  });

  test('Hydra accepts an authorization request for the MCP callback', async ({
    unauthenticatedPage: page,
  }) => {
    // This is the step the MCP flow used to die at: an unregistered redirect
    // URI is refused before any login happens, so the failure never reaches
    // the backend. A registered one gets handed on to the login/consent app.
    const authorizeUrl = new URL(
      `http://localhost:${OAUTH_PUBLIC_TEST_PORT}/oauth2/auth`
    );
    authorizeUrl.searchParams.set('client_id', 'test-client-id');
    authorizeUrl.searchParams.set('response_type', 'code');
    authorizeUrl.searchParams.set('scope', 'openid profile email');
    authorizeUrl.searchParams.set('redirect_uri', MCP_TEST_CALLBACK_URL);
    authorizeUrl.searchParams.set('state', 'mcp-redirect-uri-check');

    const response = await page.request.get(authorizeUrl.toString(), {
      maxRedirects: 0,
    });

    // A registered redirect URI is handed on to the login app with a
    // challenge; a rejected one never gets that far.
    expect(response.status()).toBe(302);
    const location = response.headers()['location'];
    expect(location).toBeTruthy();
    const redirected = new URL(location);
    expect(redirected.searchParams.get('error')).toBeNull();
    expect(redirected.searchParams.get('login_challenge')).toBeTruthy();
  });
});
