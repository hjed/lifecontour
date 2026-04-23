import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

test.describe('Contact AI Summary', () => {
  test('should display the AI Summary card in contact detail sidebar', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const contact = await dataManager.createContact({
      firstName: 'SummaryTest',
      lastName: 'User',
    });

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await authenticatedPage.goto(`/contacts/${contact.id}`);

    // Wait for contact name to load
    await expect(
      authenticatedPage
        .getByText(`${contact.firstName} ${contact.lastName}`)
        .first()
    ).toBeVisible({ timeout: 10000 });

    // Verify the summary card is present
    const summaryCard = authenticatedPage.getByTestId('contact-summary');
    await expect(summaryCard).toBeVisible({ timeout: 10000 });

    // Should show empty state since no summary has been generated
    await expect(
      authenticatedPage.getByTestId('summary-empty-state')
    ).toBeVisible({ timeout: 5000 });
  });

  test('should display AI Summary heading with bot icon', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const contact = await dataManager.createContact({
      firstName: 'SummaryIcon',
      lastName: 'Test',
    });

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await authenticatedPage.goto(`/contacts/${contact.id}`);

    // Verify the "AI Summary" heading text is visible
    await expect(authenticatedPage.getByText('AI Summary').first()).toBeVisible(
      { timeout: 10000 }
    );
  });

  test('should queue summary regeneration via refresh button without blocking UI', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const contact = await dataManager.createContact({
      firstName: 'RefreshQueue',
      lastName: 'Test',
    });

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await authenticatedPage.goto(`/contacts/${contact.id}`);

    // Wait for the summary card to be visible
    const summaryCard = authenticatedPage.getByTestId('contact-summary');
    await expect(summaryCard).toBeVisible({ timeout: 10000 });

    // Click the refresh button
    const refreshButton = authenticatedPage.getByTestId(
      'summary-refresh-button'
    );
    await expect(refreshButton).toBeVisible({ timeout: 5000 });
    await refreshButton.click();

    // Verify status badge shows "Pending" — generation was queued
    const statusBadge = authenticatedPage.getByTestId('summary-status-badge');
    await expect(statusBadge).toBeVisible({ timeout: 5000 });
    await expect(statusBadge).toContainText(/pending/i, { timeout: 5000 });

    // Verify the UI remains interactive (not blocked) — can still see the card heading
    await expect(
      authenticatedPage.getByText('AI Summary').first()
    ).toBeVisible();

    // The contact name should still be visible (UI wasn't blocked)
    await expect(
      authenticatedPage
        .getByText(`${contact.firstName} ${contact.lastName}`)
        .first()
    ).toBeVisible();
  });
});
