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

    // First, call the refresh API to create a pending summary record.
    // Without this, the component renders the empty state (no refresh button).
    const refreshResponse = await authenticatedPage.request.post(
      `/api/contacts/${contact.id}/summary/refresh`
    );
    expect(refreshResponse.status()).toBe(202);

    // Navigate to the contact page — the summary now has a PENDING status
    await authenticatedPage.goto(`/contacts/${contact.id}`);

    // Wait for the summary card to be visible (with status badge)
    const summaryCard = authenticatedPage.getByTestId('contact-summary');
    await expect(summaryCard).toBeVisible({ timeout: 10000 });

    // Verify status badge shows "Pending" — summary record exists
    const statusBadge = authenticatedPage.getByTestId('summary-status-badge');
    await expect(statusBadge).toBeVisible({ timeout: 5000 });
    await expect(statusBadge).toContainText(/pending/i, { timeout: 5000 });

    // Click the refresh button to re-queue
    const refreshButton = authenticatedPage.getByTestId(
      'summary-refresh-button'
    );
    await expect(refreshButton).toBeVisible({ timeout: 5000 });
    await refreshButton.click();

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

  test('should send POST and receive 202 when refresh button is clicked', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const contact = await dataManager.createContact({
      firstName: 'RefreshAPI',
      lastName: 'Verify',
    });

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    // Create a pending summary so the refresh button is visible
    const seedResponse = await authenticatedPage.request.post(
      `/api/contacts/${contact.id}/summary/refresh`
    );
    expect(seedResponse.status()).toBe(202);

    await authenticatedPage.goto(`/contacts/${contact.id}`);

    // Wait for the summary card
    await expect(authenticatedPage.getByTestId('contact-summary')).toBeVisible({
      timeout: 10000,
    });

    // Intercept the refresh POST and click the button
    const refreshButton = authenticatedPage.getByTestId(
      'summary-refresh-button'
    );
    await expect(refreshButton).toBeVisible({ timeout: 5000 });

    const [response] = await Promise.all([
      authenticatedPage.waitForResponse(
        resp =>
          resp.url().includes('/summary/refresh') &&
          resp.request().method() === 'POST',
        { timeout: 10000 }
      ),
      refreshButton.click(),
    ]);

    // Verify the API returned 202
    expect(response.status()).toBe(202);

    // Verify status badge still shows Pending after re-queue
    await expect(
      authenticatedPage.getByTestId('summary-status-badge')
    ).toContainText(/pending/i, { timeout: 5000 });
  });

  test('should not show generated_at timestamp for user override summary', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const contact = await dataManager.createContact({
      firstName: 'OverrideTime',
      lastName: 'NoTimestamp',
    });

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    // Set user override text via PATCH — status becomes GENERATED but generated_at is null
    const patchResponse = await authenticatedPage.request.patch(
      `/api/contacts/${contact.id}/summary`,
      {
        data: {
          data: {
            user_override_text: 'Manual summary written by user',
          },
        },
      }
    );
    expect(patchResponse.status()).toBe(200);

    await authenticatedPage.goto(`/contacts/${contact.id}`);

    // Wait for the summary card
    await expect(authenticatedPage.getByTestId('contact-summary')).toBeVisible({
      timeout: 10000,
    });

    // Verify status badge shows Generated
    await expect(
      authenticatedPage.getByTestId('summary-status-badge')
    ).toContainText(/generated/i, { timeout: 5000 });

    // Verify user override text is displayed
    await expect(
      authenticatedPage.getByText('Manual summary written by user')
    ).toBeVisible({ timeout: 5000 });

    // Verify generated_at timestamp is NOT shown (since it's null for user override)
    await expect(
      authenticatedPage.getByTestId('summary-generated-at')
    ).not.toBeVisible({ timeout: 3000 });
  });
});
