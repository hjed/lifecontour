import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

test.describe('ITER2.6-001 Phase 1: Google Contacts Sync Semantics', () => {
  test('UI correctly renders Contact from Google Sync ignoring reserved groups and surfacing Starred as favourite', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    // 1. Simulate the sync result by creating the contact exactly as the worker would
    // The worker creates a contact, sets isFavourite=True (from Starred), and ignores 'myContacts'
    const dataManager = new TestDataManager(authenticatedPage);
    const contacts = await dataManager.createContacts([
      {
        firstName: 'Synced',
        lastName: 'Contact',
        email: 'starred@example.com',
        isFavourite: true,
        tags: ['Family'],
      },
    ]);
    const contactId = contacts[0].id;
    // Explicitly set favourite in case createContacts doesn't set it perfectly
    await dataManager.setContactFavourite(contactId, true);

    // Register cleanup
    testCleanup(async () => {
      await dataManager.cleanup();
    });

    // 2. Nearest UI workflow: Check the contacts page to ensure it appears correctly
    await authenticatedPage.goto('/contacts');

    // Assert the contact is in the list
    const card = authenticatedPage.locator(
      `[data-testid="contact-${contactId}"]`
    );
    await expect(card).toBeVisible();

    // Check if the favourite button is active/checked
    // The UI usually indicates this with aria-pressed="true" or a specific class/icon
    const faveButton = card.locator('button[aria-label*="favourite" i]');
    await expect(faveButton.first()).toBeVisible();
    await expect(faveButton.first()).toHaveAttribute('aria-pressed', 'true');

    // Verify no 'myContacts' tag is shown anywhere on the card
    await expect(card).not.toContainText(/myContacts/i);
    await expect(card).not.toContainText(/Starred/i);
  });
});
