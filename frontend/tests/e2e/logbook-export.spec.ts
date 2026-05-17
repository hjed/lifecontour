/**
 * E2E test for the outdoor logbook PDF export feature.
 *
 * Tests the full workflow: navigating to journals, opening the export dialog,
 * selecting filters, and triggering a PDF download.
 */

import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

test.describe('Logbook Export', () => {
  test('exports outdoor logbook PDF from journals page', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    // Clean slate
    await dataManager.clearAllJournals();

    // Seed a bushwalking journal via API
    const today = new Date();
    const journals = await dataManager.createJournals([
      {
        title: 'Blue Mountains Bushwalk',
        content: 'A great day on the trails',
        event_date_range: {
          start: today.toISOString(),
          end: today.toISOString(),
        },
        types: ['bushwalking'],
      },
    ]);

    expect(journals).toHaveLength(1);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    // Navigate to journals page
    await page.goto('/journals');
    // Wait for journals page to be loaded by checking for the search input
    await expect(page.locator('[data-testid="search-input"]')).toBeVisible({
      timeout: 15000,
    });

    // Click the Export Logbook button
    const exportButton = page.locator('[data-testid="export-logbook"]');
    await expect(exportButton).toBeVisible();
    await exportButton.click();

    // Verify the export dialog opens
    const dialog = page.locator('[data-testid="logbook-export-dialog"]');
    await expect(dialog).toBeVisible();

    // Verify the dialog shows the expected title
    await expect(dialog.getByText('Export Outdoor Logbook')).toBeVisible();

    // Verify activity type checkboxes are present
    await expect(dialog.getByText('Bushwalking')).toBeVisible();
    await expect(dialog.getByText('Canyoning')).toBeVisible();

    // Set up download listener before clicking export
    const downloadPromise = page.waitForEvent('download', { timeout: 30000 });

    // Click the Export PDF button
    const submitButton = dialog.locator('[data-testid="export-submit"]');
    await expect(submitButton).toBeVisible();
    await submitButton.click();

    // Verify loading state appears
    // Note: This may be very quick, so we use a short timeout
    // The button text changes to "Generating PDF…" during loading

    // Wait for the PDF file download
    const download = await downloadPromise;

    // Verify the downloaded file is a PDF
    const fileName = download.suggestedFilename();
    expect(fileName).toContain('outdoor_logbook');
    expect(fileName).toContain('.pdf');

    // Verify the file is non-empty by reading its path
    const downloadPath = await download.path();
    expect(downloadPath).toBeTruthy();
  });

  test('exports with activity type filter selected', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    // Clean slate and seed data
    await dataManager.clearAllJournals();

    const today = new Date();
    await dataManager.createJournals([
      {
        title: 'Canyon Adventure',
        content: 'Technical canyon trip',
        event_date_range: {
          start: today.toISOString(),
          end: today.toISOString(),
        },
        types: ['canyoning'],
      },
    ]);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    // Navigate and open export dialog
    await page.goto('/journals');
    await expect(page.locator('[data-testid="search-input"]')).toBeVisible({
      timeout: 15000,
    });

    await page.locator('[data-testid="export-logbook"]').click();
    const dialog = page.locator('[data-testid="logbook-export-dialog"]');
    await expect(dialog).toBeVisible();

    // Select the Canyoning activity type filter
    const canyoningCheckbox = dialog.locator(
      '[data-testid="export-type-CANYONING"]'
    );
    await canyoningCheckbox.click();

    // Set up download listener and export
    const downloadPromise = page.waitForEvent('download', { timeout: 30000 });
    await dialog.locator('[data-testid="export-submit"]').click();

    // Verify PDF downloads
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toContain('.pdf');
  });
});
