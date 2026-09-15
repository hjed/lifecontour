import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

// Note: the AI Summary card rendering (empty state, heading, status badges,
// user-override text, refresh button enable/disable, generated-at visibility,
// generation switch states) is unit-tested in ContactSummary.test.tsx. These
// e2e tests cover only the real summary API contract (POST 202 / PATCH 200)
// that the component test mocks out.
test.describe('Contact AI Summary', () => {
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
    // Use a retry loop to handle transient 404s (contact not yet visible in DB)
    let refreshResponse;
    for (let i = 0; i < 3; i++) {
      refreshResponse = await authenticatedPage.request.post(
        `/api/contacts/${contact.id}/summary/refresh`
      );
      if (refreshResponse.status() === 202) break;
      await new Promise(r => setTimeout(r, 1000));
    }
    expect(refreshResponse?.status()).toBe(202);

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
    let seedResponse;
    for (let i = 0; i < 3; i++) {
      seedResponse = await authenticatedPage.request.post(
        `/api/contacts/${contact.id}/summary/refresh`
      );
      if (seedResponse.status() === 202) break;
      await new Promise(r => setTimeout(r, 1000));
    }
    expect(seedResponse?.status()).toBe(202);

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

    // First create a pending summary so the record exists
    let seedResponse;
    for (let i = 0; i < 3; i++) {
      seedResponse = await authenticatedPage.request.post(
        `/api/contacts/${contact.id}/summary/refresh`
      );
      if (seedResponse.status() === 202) break;
      await new Promise(r => setTimeout(r, 1000));
    }
    expect(seedResponse?.status()).toBe(202);

    // Set user override text via PATCH — status becomes GENERATED but generated_at is null
    const patchResponse = await authenticatedPage.request.patch(
      `/api/contacts/${contact.id}/summary`,
      {
        // Note: The outer `data` is Playwright's request option property.
        // The inner `data` matches the backend JSON:API schema requirement.
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

  test('should turn AI summary generation back on with the switch', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const contact = await dataManager.createContact({
      firstName: 'SummaryToggle',
      lastName: 'Reenable',
    });

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    // Seed a summary the user has turned off. The PATCH is idempotent, so
    // retrying it rides out transient 404s while the new contact becomes
    // visible.
    await expect(async () => {
      const disableResponse = await authenticatedPage.request.patch(
        `/api/contacts/${contact.id}/summary`,
        {
          // Outer `data` is Playwright's option; inner `data` is JSON:API.
          data: { data: { is_disabled: true } },
          timeout: 3000,
        }
      );
      expect(disableResponse.status()).toBe(200);
    }).toPass({ timeout: 10000 });

    await authenticatedPage.goto(`/contacts/${contact.id}`);

    const generationSwitch = authenticatedPage.getByRole('switch', {
      name: 'AI generation',
    });
    const refreshButton = authenticatedPage.getByTestId(
      'summary-refresh-button'
    );
    await expect(generationSwitch).toHaveAttribute('aria-checked', 'false', {
      timeout: 10000,
    });
    await expect(refreshButton).toBeDisabled();

    const [response] = await Promise.all([
      authenticatedPage.waitForResponse(
        resp =>
          resp.url().endsWith(`/api/contacts/${contact.id}/summary`) &&
          resp.request().method() === 'PATCH',
        { timeout: 10000 }
      ),
      generationSwitch.click(),
    ]);
    expect(response.status()).toBe(200);

    // Durable state from the server, not the transient status badge: the
    // re-enabled summary is no longer user-disabled, so the switch is on and
    // refresh is allowed again.
    await expect(generationSwitch).toHaveAttribute('aria-checked', 'true', {
      timeout: 10000,
    });
    await expect(refreshButton).toBeEnabled();
  });
});
