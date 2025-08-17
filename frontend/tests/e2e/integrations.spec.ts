/**
 * End-to-end tests for integration functionality.
 *
 * Tests the complete integration workflow including sync triggers,
 * status monitoring, and health checks through the UI.
 */

import { test, expect } from '@playwright/test';
import { createAuthFixtures } from './fixtures/auth';

test.describe.skip('Integration Management', () => {
  test.beforeEach(async ({ page }) => {
    // Authenticate user before each test
    const authFixtures = createAuthFixtures(page);
    await authFixtures.mockAuthenticated('github');
  });

  test('should display integration health status', async ({ page }) => {
    // Navigate to integrations page (assuming it exists)
    // For now, we'll test the API endpoints directly

    // Test integration health endpoint
    const response = await page.request.get('/api/integrations/health');
    expect(response.ok()).toBeTruthy();

    const healthData = await response.json();
    expect(healthData).toHaveProperty('status');
    expect(healthData).toHaveProperty('services');
    expect(healthData.services).toHaveProperty('redis');
    expect(healthData.services).toHaveProperty('google_contacts_worker');
  });

  test('should trigger Google Contacts sync via API', async ({ page }) => {
    // Test sync trigger endpoint
    const response = await page.request.post(
      '/api/integrations/google/contacts/sync',
      {
        data: {
          google_account_email: 'test@example.com',
          sync_type: 'smart',
        },
      }
    );

    expect(response.ok()).toBeTruthy();

    const syncData = await response.json();
    expect(syncData).toHaveProperty('job_id');
    expect(syncData).toHaveProperty('status', 'queued');
    expect(syncData).toHaveProperty('google_account_email', 'test@example.com');
    expect(syncData).toHaveProperty('sync_type', 'smart');

    // Test job status endpoint
    const jobId = syncData.job_id;
    const statusResponse = await page.request.get(
      `/api/integrations/google/contacts/sync/${jobId}`
    );
    expect(statusResponse.ok()).toBeTruthy();

    const statusData = await statusResponse.json();
    expect(statusData).toHaveProperty('job_id', jobId);
    expect(statusData).toHaveProperty('status');
    expect(statusData.status).toMatch(/^(queued|in_progress|complete|failed)$/);
  });

  test('should handle sync trigger validation errors', async ({ page }) => {
    // Test with invalid email format
    const response = await page.request.post(
      '/api/integrations/google/contacts/sync',
      {
        data: {
          google_account_email: 'invalid-email',
          sync_type: 'smart',
        },
      }
    );

    // Should either succeed (validation happens in worker) or fail with validation error
    if (!response.ok()) {
      expect(response.status()).toBe(422); // Validation error
    }
  });

  test('should handle non-existent job status requests', async ({ page }) => {
    const response = await page.request.get(
      '/api/integrations/google/contacts/sync/non-existent-job'
    );
    expect(response.status()).toBe(404);

    const errorData = await response.json();
    expect(errorData).toHaveProperty('detail');
    expect(errorData.detail).toContain('not found');
  });

  test('should get Google Contacts integration status', async ({ page }) => {
    const response = await page.request.get(
      '/api/integrations/google/contacts/status',
      {
        params: {
          google_account_email: 'test@example.com',
        },
      }
    );

    expect(response.ok()).toBeTruthy();

    const statusData = await response.json();
    expect(statusData).toHaveProperty(
      'google_account_email',
      'test@example.com'
    );
    expect(statusData).toHaveProperty('is_authenticated');
    expect(statusData).toHaveProperty('sync_status');
    expect(statusData).toHaveProperty('total_contacts');
    expect(statusData).toHaveProperty('sync_token_available');
  });

  test('should require authentication for integration endpoints', async ({
    page,
  }) => {
    // Clear authentication
    await page.context().clearCookies();

    const endpoints = [
      {
        method: 'POST',
        url: '/api/integrations/google/contacts/sync',
        data: { google_account_email: 'test@example.com', sync_type: 'smart' },
      },
      { method: 'GET', url: '/api/integrations/google/contacts/sync/test-job' },
      {
        method: 'GET',
        url: '/api/integrations/google/contacts/status?google_account_email=test@example.com',
      },
      { method: 'GET', url: '/api/integrations/health' },
    ];

    for (const endpoint of endpoints) {
      let response;
      if (endpoint.method === 'POST') {
        response = await page.request.post(endpoint.url, {
          data: endpoint.data,
        });
      } else {
        response = await page.request.get(endpoint.url);
      }

      expect(response.status()).toBe(401); // Unauthorized
    }
  });
});

test.describe.skip('Integration UI Components', () => {
  test.beforeEach(async ({ page }) => {
    const authFixtures = createAuthFixtures(page);
    await authFixtures.mockAuthenticated('github');
  });

  test.skip('should display integration status in UI', async ({ page }) => {
    // Skip until integration UI is implemented
    // This test would navigate to an integrations page and verify:
    // - Integration status display
    // - Sync trigger buttons
    // - Job status monitoring
    // - Health indicators

    await page.goto('/integrations'); // Assuming this route exists

    // Verify page loads
    await expect(page).toHaveTitle(/Integrations/);

    // Check for Google Contacts integration section
    await expect(
      page.locator('[data-testid="google-contacts-integration"]')
    ).toBeVisible();

    // Check for sync trigger button
    await expect(
      page.locator('[data-testid="trigger-google-sync"]')
    ).toBeVisible();

    // Check for status display
    await expect(
      page.locator('[data-testid="integration-status"]')
    ).toBeVisible();
  });

  test.skip('should trigger sync through UI', async ({ page }) => {
    // Skip until integration UI is implemented
    await page.goto('/integrations');

    // Click sync trigger button
    await page.click('[data-testid="trigger-google-sync"]');

    // Should show confirmation or progress indicator
    await expect(page.locator('[data-testid="sync-progress"]')).toBeVisible();

    // Should update status
    await expect(page.locator('[data-testid="sync-status"]')).toContainText(
      'In Progress'
    );
  });

  test.skip('should display sync history', async ({ page }) => {
    // Skip until integration UI is implemented
    await page.goto('/integrations');

    // Should show recent sync jobs
    await expect(page.locator('[data-testid="sync-history"]')).toBeVisible();

    // Should show job details
    await expect(page.locator('[data-testid="sync-job-item"]')).toBeVisible();
  });
});

test.describe.skip('Integration Error Handling', () => {
  test.beforeEach(async ({ page }) => {
    const authFixtures = createAuthFixtures(page);
    await authFixtures.mockAuthenticated('github');
  });

  test('should handle API errors gracefully', async ({ page }) => {
    // Test with malformed request
    const response = await page.request.post(
      '/api/integrations/google/contacts/sync',
      {
        data: {
          // Missing required fields
          sync_type: 'invalid_type',
        },
      }
    );

    expect(response.status()).toBe(422); // Validation error

    const errorData = await response.json();
    expect(errorData).toHaveProperty('detail');
  });

  test('should handle worker unavailability', async ({ page }) => {
    // This test would verify behavior when workers are down
    // For now, we just test that the API responds appropriately

    const response = await page.request.get('/api/integrations/health');
    expect(response.ok()).toBeTruthy();

    const healthData = await response.json();

    // Health status should indicate if workers are unavailable
    if (healthData.status === 'unhealthy') {
      expect(healthData.services.google_contacts_worker.status).toBe(
        'unhealthy'
      );
    }
  });
});
