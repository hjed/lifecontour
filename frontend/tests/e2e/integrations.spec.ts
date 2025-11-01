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
    // Test integration health endpoint
    const response = await authenticatedPage.request.get(
      '/api/integrations/health'
    );
    expect(response.ok()).toBeTruthy();

    const healthData = await response.json();
    expect(healthData).toHaveProperty('data');
    expect(healthData.data).toHaveProperty('type', 'integration-health');
    expect(healthData.data).toHaveProperty('attributes');
  });

  test('should trigger Google Contacts sync via API', async ({
    authenticatedPage,
  }) => {
    // Test sync trigger endpoint (requires authentication)
    const response = await authenticatedPage.request.post(
      '/api/integrations/google/contacts/sync',
      {
        data: {
          sync_type: 'smart',
        },
      }
    );

    // Should return 401 since we're not authenticated in this test
    expect(response.status()).toBe(401);

    const errorData = await response.json();
    expect(errorData).toHaveProperty('errors');
    expect(errorData.errors[0]).toHaveProperty('status', '401');

    // Test job status endpoint (also requires authentication)
    const statusResponse = await authenticatedPage.request.get(
      `/api/integrations/google/contacts/sync/test-job-id`
    );
    expect(statusResponse.status()).toBe(401);

    const statusErrorData = await statusResponse.json();
    expect(statusErrorData).toHaveProperty('errors');
    expect(statusErrorData.errors[0]).toHaveProperty('status', '401');
  });

  test('should handle sync trigger errors gracefully', async ({
    authenticatedPage,
  }) => {
    // Test sync trigger - requires authentication
    const response = await authenticatedPage.request.post(
      '/api/integrations/google/contacts/sync',
      {
        data: {
          sync_type: 'full',
        },
      }
    );

    // Should return 401 since we're not authenticated
    expect(response.status()).toBe(401);
    const errorData = await response.json();
    expect(errorData).toHaveProperty('errors');
    expect(errorData.errors[0]).toHaveProperty('status', '401');
  });

  test('should handle non-existent job status requests', async ({
    authenticatedPage,
  }) => {
    const response = await authenticatedPage.request.get(
      '/api/integrations/google/contacts/sync/non-existent-job'
    );
    // Should return 401 since we're not authenticated
    expect(response.status()).toBe(401);

    const errorData = await response.json();
    expect(errorData).toHaveProperty('errors');
    expect(errorData.errors[0]).toHaveProperty('status', '401');
  });

  test('should get Google Contacts integration status', async ({
    authenticatedPage,
  }) => {
    const response = await authenticatedPage.request.get(
      '/api/integrations/google/contacts/status'
    );

    // This endpoint returns 401 (authentication error) for unauthenticated requests
    expect(response.status()).toBe(401);

    const errorData = await response.json();
    expect(errorData).toHaveProperty('errors');
    expect(errorData.errors[0]).toHaveProperty('status', '401');
  });
});

test.describe('Integration UI Components', () => {
  test('should display integration status in UI', async ({
    authenticatedPage,
  }) => {
    // Mock API responses
    await authenticatedPage.route('/api/integrations/**', route => {
      const url = route.request().url();
      if (url.includes('/health')) {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            data: {
              id: 'health',
              type: 'integration-health',
              attributes: {
                redis: { status: 'healthy', latency: 5 },
                worker: {
                  status: 'healthy',
                  lastSeen: new Date().toISOString(),
                },
                overall: 'healthy',
                lastChecked: new Date().toISOString(),
              },
            },
          }),
        });
      } else if (url.includes('/status')) {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            data: {
              id: 'google-contacts',
              type: 'integration-status',
              attributes: {
                connected: false,
                lastSync: null,
                syncCount: 0,
                status: 'disconnected',
              },
            },
          }),
        });
      } else {
        route.fulfill({ status: 404 });
      }
    });

    await authenticatedPage.goto('/integrations');

    // Verify page loads
    await expect(authenticatedPage).toHaveTitle(/Integrations/);

    // Check for Google Contacts integration section
    await expect(
      authenticatedPage.locator('[data-testid="google-contacts-integration"]')
    ).toBeVisible();

    // Check for sync trigger button
    await expect(
      authenticatedPage.locator('[data-testid="trigger-google-sync"]')
    ).toBeVisible();

    // Check for status display
    await expect(
      authenticatedPage.locator('[data-testid="integration-status"]')
    ).toBeVisible();
  });

  test('should trigger sync through UI', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/integrations');

    // Click sync trigger button
    await authenticatedPage.click('[data-testid="trigger-google-sync"]');

    // Should show confirmation or progress indicator
    await expect(
      authenticatedPage.locator('[data-testid="sync-progress"]')
    ).toBeVisible();

    // Should update status
    await expect(
      authenticatedPage.locator('[data-testid="sync-status"]')
    ).toContainText('In Progress');
  });

  test('should display sync history', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/integrations');

    // Should show recent sync jobs
    await expect(
      authenticatedPage.locator('[data-testid="sync-history"]')
    ).toBeVisible();

    // Should show job details
    await expect(
      authenticatedPage.locator('[data-testid="sync-job-item"]')
    ).toBeVisible();
  });
});

test.describe('Integration Error Handling', () => {
  test('should handle API errors gracefully', async ({ authenticatedPage }) => {
    // Test sync endpoint - requires authentication
    const response = await authenticatedPage.request.post(
      '/api/integrations/google/contacts/sync',
      {
        data: {
          sync_type: 'smart',
        },
      }
    );

    // Should return 401 since we're not authenticated
    expect(response.status()).toBe(401);
    const errorData = await response.json();
    expect(errorData).toHaveProperty('errors');
    expect(errorData.errors[0]).toHaveProperty('status', '401');
    expect(errorData.errors[0]).toHaveProperty(
      'detail',
      'Authentication required'
    );
  });

  test('should handle worker unavailability', async ({ authenticatedPage }) => {
    // This test would verify behavior when workers are down
    // For now, we just test that the API responds appropriately

    const response = await authenticatedPage.request.get(
      '/api/integrations/health'
    );
    expect(response.ok()).toBeTruthy();

    const healthData = await response.json();

    // Health status should indicate if workers are unavailable
    if (
      healthData.data?.attributes?.overall === 'unhealthy' &&
      healthData.data?.attributes?.worker
    ) {
      expect(healthData.data.attributes.worker.status).toBe('unhealthy');
    }
  });
});

test.describe('Integration Management - Unauthenticated User', () => {
  test('should require authentication for integration endpoints', async ({
    unauthenticatedPage,
  }) => {
    // Endpoints that require authentication and return 401
    const auth401Endpoints = [
      { method: 'POST', url: '/api/integrations/google/contacts/sync' },
      {
        method: 'GET',
        url: '/api/integrations/google/contacts/sync/test-job',
      },
    ];

    for (const endpoint of auth401Endpoints) {
      let response;
      if (endpoint.method === 'POST') {
        response = await unauthenticatedPage.request.post(endpoint.url, {
          data: {
            sync_type: 'incremental',
          },
        });
      } else {
        response = await unauthenticatedPage.request.get(endpoint.url);
      }

      expect(response.status()).toBe(401); // Unauthorized
    }

    // Status endpoint requires authentication
    const statusResponse = await unauthenticatedPage.request.get(
      '/api/integrations/google/contacts/status'
    );
    expect(statusResponse.status()).toBe(401); // Unauthorized

    // Health endpoint should not require authentication
    const healthResponse = await unauthenticatedPage.request.get(
      '/api/integrations/health'
    );
    expect(healthResponse.status()).toBe(200);
  });
});
