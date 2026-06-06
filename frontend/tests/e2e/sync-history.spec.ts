/**
 * E2E tests for sync history functionality.
 *
 * Tests the sync history endpoint and UI integration.
 */

import { expect, test } from './fixtures';

interface SyncJob {
  attributes?: {
    status?: string;
    syncType?: string;
    createdAt?: string | Date;
  };
}

test.describe('Sync History - Authenticated User', () => {
  test('should fetch sync history successfully', async ({
    authenticatedPage,
  }) => {
    // Test sync history endpoint
    const response = await authenticatedPage.request.get(
      '/api/integrations/google/sync-history?limit=5'
    );

    expect(response.ok()).toBeTruthy();

    const data = await response.json();

    // Verify JSON API format
    expect(data).toHaveProperty('data');
    expect(data).toHaveProperty('meta');
    expect(Array.isArray(data.data)).toBeTruthy();
    expect(data.meta).toHaveProperty('total');
    expect(data.meta).toHaveProperty('page');
    expect(data.meta).toHaveProperty('pageSize');
  });

  test('should filter sync history by status', async ({
    authenticatedPage,
  }) => {
    // Test filtering by status
    const response = await authenticatedPage.request.get(
      '/api/integrations/google/sync-history?status=completed&limit=5'
    );

    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data).toHaveProperty('data');

    const statuses = data.data.map((job: SyncJob) => job.attributes?.status);
    expect(
      statuses.every((status: string) => status === 'completed')
    ).toBeTruthy();
  });

  test('should filter sync history by sync type', async ({
    authenticatedPage,
  }) => {
    // Test filtering by sync type
    const response = await authenticatedPage.request.get(
      '/api/integrations/google/sync-history?sync_type=smart&limit=5'
    );

    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data).toHaveProperty('data');

    const syncTypes = data.data.map((job: SyncJob) => job.attributes?.syncType);
    expect(syncTypes.every((type: string) => type === 'smart')).toBeTruthy();
  });

  test('should filter sync history by date range', async ({
    authenticatedPage,
  }) => {
    // Test filtering by date range
    const dateFrom = '2024-01-01T00:00:00Z';
    const dateTo = '2024-12-31T23:59:59Z';

    const response = await authenticatedPage.request.get(
      `/api/integrations/google/sync-history?date_from=${dateFrom}&date_to=${dateTo}&limit=5`
    );

    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data).toHaveProperty('data');

    const dates = data.data.map(
      (job: SyncJob) => new Date(job.attributes?.createdAt as string)
    );
    expect(
      dates.every((d: Date) => d >= new Date(dateFrom) && d <= new Date(dateTo))
    ).toBeTruthy();
  });

  test('should paginate sync history', async ({ authenticatedPage }) => {
    // Test pagination
    const response1 = await authenticatedPage.request.get(
      '/api/integrations/google/sync-history?limit=2&offset=0'
    );

    expect(response1.ok()).toBeTruthy();

    const data1 = await response1.json();
    expect(data1.meta.page).toBe(1);
    expect(data1.meta.pageSize).toBe(2);

    // Get second page
    const response2 = await authenticatedPage.request.get(
      '/api/integrations/google/sync-history?limit=2&offset=2'
    );

    expect(response2.ok()).toBeTruthy();

    const data2 = await response2.json();
    expect(data2.meta.page).toBe(2);
    expect(data2.meta.pageSize).toBe(2);
  });

  test('should return 400 for invalid date format', async ({
    authenticatedPage,
  }) => {
    // Test invalid date format
    const response = await authenticatedPage.request.get(
      '/api/integrations/google/sync-history?date_from=invalid-date'
    );

    expect(response.status()).toBe(400);

    const data = await response.json();
    // Backend returns JSON API error format
    expect(data).toHaveProperty('errors');
    expect(Array.isArray(data.errors)).toBeTruthy();
    expect(data.errors[0]).toHaveProperty('detail');
    expect(data.errors[0].detail).toContain('Invalid date_from format');
  });
});

test.describe('Sync History - Unauthenticated User', () => {
  test('should require authentication', async ({ unauthenticatedPage }) => {
    // Test that unauthenticated users cannot access sync history
    const response = await unauthenticatedPage.request.get(
      '/api/integrations/google/sync-history'
    );

    expect(response.status()).toBe(401);
  });
});
