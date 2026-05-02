/**
 * End-to-end tests for integration functionality.
 *
 * Tests the complete integration workflow including sync triggers,
 * status monitoring, and health checks through the UI.
 */

import { test, expect } from './fixtures';

test.describe('Integration Management - Authenticated User', () => {
  test('should display integration health status', async ({
    authenticatedPage,
  }) => {
    // Test integration health endpoint - this endpoint does NOT require authentication
    const response = await authenticatedPage.request.get(
      '/api/integrations/health'
    );
    expect(response.ok()).toBeTruthy();

    const healthData = await response.json();
    // JSON API format
    expect(healthData).toHaveProperty('data');
    expect(healthData.data).toHaveProperty('attributes');
    expect(healthData.data.attributes).toHaveProperty('overall');
    expect(healthData.data.attributes).toHaveProperty('redis');
    expect(healthData.data.attributes).toHaveProperty('worker');
  });

  test('should trigger Google Contacts sync via API', async ({
    authenticatedPage,
  }) => {
    // Test sync trigger endpoint (requires authentication)
    const response = await authenticatedPage.request.post(
      '/api/integrations/google/contacts/sync',
      {
        headers: {
          'Content-Type': 'application/json',
        },
        data: {
          sync_type: 'smart',
        },
      }
    );

    // Accept various response codes:
    // 200 = success
    // 400 = bad request (e.g., validation error, missing config)
    // 500 = internal server error
    // 503 = service unavailable (Redis down)
    expect([200, 400, 500, 503]).toContain(response.status());

    if (response.ok()) {
      const jobData = await response.json();
      expect(jobData).toHaveProperty('data');
      expect(jobData.data).toHaveProperty('id');
      expect(jobData.data).toHaveProperty('attributes');
      expect(jobData.data.attributes).toHaveProperty('status');
    }
  });

  test('should get Google Contacts integration status', async ({
    authenticatedPage,
  }) => {
    const response = await authenticatedPage.request.get(
      '/api/integrations/google/contacts/status'
    );

    // Should succeed with authentication
    expect(response.ok()).toBeTruthy();

    const statusData = await response.json();
    // Check JSON API format
    expect(statusData).toHaveProperty('data');
    expect(statusData.data).toHaveProperty('attributes');
    expect(statusData.data.attributes).toHaveProperty('status');
    expect(statusData.data.attributes).toHaveProperty('connected');
    // Verify status is one of the expected values
    // ("connected" is a boolean field; the status field is an IntegrationStatus)
    expect(['active', 'disconnected', 'error', 'inactive']).toContain(
      statusData.data.attributes.status
    );
  });

  test('should handle OAuth authorization flow for Google Contacts', async ({
    authenticatedPage,
  }) => {
    // Test OAuth authorization endpoint
    const response = await authenticatedPage.request.post(
      '/api/integrations/google/contacts/oauth/authorize',
      {
        headers: {
          'Content-Type': 'application/json',
        },
        data: {
          redirect_url: '/integrations',
        },
      }
    );

    // Accept various response codes:
    // 200 = success (Google OAuth configured)
    // 400 = bad request (Google OAuth not configured)
    expect([200, 400]).toContain(response.status());

    if (response.ok()) {
      const authData = await response.json();
      expect(authData).toHaveProperty('authorization_url');
      expect(authData).toHaveProperty('state');
      expect(authData.authorization_url).toContain('accounts.google.com');
    } else {
      // If Google OAuth is not configured, expect appropriate error (JSON API format)
      const errorData = await response.json();
      expect(errorData.errors).toBeDefined();
      expect(errorData.errors.length).toBeGreaterThan(0);
      expect(errorData.errors[0].detail).toContain(
        'Google OAuth provider not configured'
      );
    }
  });

  test('should handle OAuth disconnect for Google Contacts', async ({
    authenticatedPage,
  }) => {
    // Test OAuth disconnect endpoint
    const response = await authenticatedPage.request.delete(
      '/api/integrations/google/contacts/oauth/disconnect'
    );

    // Accept various response codes:
    // 200 = success (disconnected)
    // 400 = bad request (not connected)
    expect([200, 400]).toContain(response.status());

    const responseData = await response.json();
    expect(responseData).toHaveProperty('success');
    expect(responseData).toHaveProperty('message');
  });

  test('should display OAuth connection controls in UI', async ({
    authenticatedPage,
  }) => {
    // Navigate to integrations page
    await authenticatedPage.goto('/integrations');

    // Wait for page to load
    await authenticatedPage.waitForSelector(
      '[data-testid="integration-panel-google"]'
    );

    // Check if connect or disconnect button is present
    const connectButton = authenticatedPage.locator(
      '[data-testid="connect-google"]'
    );
    const disconnectButton = authenticatedPage.locator(
      '[data-testid="disconnect-google"]'
    );

    // Either connect or disconnect button should be visible
    const connectVisible = await connectButton.isVisible();
    const disconnectVisible = await disconnectButton.isVisible();

    expect(connectVisible || disconnectVisible).toBeTruthy();

    if (connectVisible) {
      // Test connect button functionality
      expect(await connectButton.textContent()).toContain('Connect Account');

      // Click should trigger OAuth flow (but we won't complete it in tests)
      // Just verify the button is clickable
      expect(await connectButton.isEnabled()).toBeTruthy();
    }

    if (disconnectVisible) {
      // Test disconnect button functionality
      expect(await disconnectButton.textContent()).toContain('Disconnect');
      expect(await disconnectButton.isEnabled()).toBeTruthy();
    }
  });
});

test.describe('Integration Registry API - GET /api/integrations', () => {
  test('should return a valid JSON API response with data array', async ({
    authenticatedPage,
  }) => {
    const response = await authenticatedPage.request.get('/api/integrations');
    expect(response.ok()).toBeTruthy();

    const body = await response.json();

    // Root must have "data" key containing an array
    expect(body).toHaveProperty('data');
    expect(Array.isArray(body.data)).toBe(true);
  });

  test('should include Google integration with required fields', async ({
    authenticatedPage,
  }) => {
    const response = await authenticatedPage.request.get('/api/integrations');
    expect(response.ok()).toBeTruthy();

    const body = await response.json();
    expect(body.data.length).toBeGreaterThanOrEqual(1);

    // Find the Google entry
    const google = body.data.find(
      (entry: { id: string }) => entry.id === 'google'
    );
    expect(google).toBeDefined();

    // Verify JSON API type
    expect(google.type).toBe('integration');

    // Verify all required attributes exist
    const attrs = google.attributes;
    expect(attrs).toHaveProperty('name');
    expect(attrs.name).toBe('Google');
    expect(attrs).toHaveProperty('status');
    expect(attrs).toHaveProperty('capabilities');
    expect(attrs).toHaveProperty('sync_summary');
    expect(attrs).toHaveProperty('needs_reauth');
    expect(attrs).toHaveProperty('needs_reconsent');

    // Status must be one of the valid values
    expect(['connected', 'disconnected', 'error', 'token_expired']).toContain(
      attrs.status
    );

    // Capabilities must be an array
    expect(Array.isArray(attrs.capabilities)).toBe(true);
    expect(attrs.capabilities.length).toBeGreaterThan(0);

    // Sync summary must have expected shape
    expect(attrs.sync_summary).toHaveProperty('sync_count');
    expect(attrs.sync_summary).toHaveProperty('error_count');
    expect(typeof attrs.sync_summary.sync_count).toBe('number');
    expect(typeof attrs.sync_summary.error_count).toBe('number');
  });

  test('should return Google with contacts_sync and calendar_sync capabilities', async ({
    authenticatedPage,
  }) => {
    const response = await authenticatedPage.request.get('/api/integrations');
    expect(response.ok()).toBeTruthy();

    const body = await response.json();
    const google = body.data.find(
      (entry: { id: string }) => entry.id === 'google'
    );
    expect(google).toBeDefined();

    expect(google.attributes.capabilities).toContain('contacts_sync');
    expect(google.attributes.capabilities).toContain('calendar_sync');
  });
});
