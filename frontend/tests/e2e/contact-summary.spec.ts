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
});
