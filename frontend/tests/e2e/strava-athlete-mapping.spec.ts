/**
 * E2E test for Strava athlete mappings.
 *
 * This test verifies the full user flow for mapping an unmatched Strava athlete
 * to a CRM contact from the journal detail page, and then viewing/deleting
 * that mapping from the integration settings panel.
 *
 * Covers product specification requirements:
 * - "Journal detail page: when a Strava-imported journal has unmatched athletes, show Link participant action"
 * - "Integration settings management panel: Strava setting page, Strava Athlete Mappings, view and delete mappings."
 */

import { expect, test } from './fixtures';
import { TestDataManager } from './data-management';

test.describe('Strava Athlete Mappings', () => {
  test('link unmatched athlete to contact and manage in settings', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);
    await dataManager.clearAllJournals();

    // 1. Setup Test Data
    // Create a contact to link
    const contact = await dataManager.contacts.createContact({
      first_name: 'Strava',
      last_name: 'Runner',
      emails: [{ email: 'runner@strava.test', is_primary: true }],
    });

    // Create a journal
    const journal = await dataManager.createJournal({
      title: 'Morning Group Run',
      content: 'Group run with Strava friends.',
      event_date_range: {
        start: new Date().toISOString(),
        end: new Date().toISOString(),
      },
    });

    testCleanup(async () => {
      await dataManager.cleanup();
      // Clean up the mapping from the backend if it was created
      try {
        await authenticatedPage.request.delete(
          `/api/integrations/strava/athlete-mappings/test-athlete-123`
        );
      } catch (e) {
        // Ignore if already deleted
      }
    });

    // 2. Intercept unmatched athletes API to simulate an unmatched athlete on this journal
    await authenticatedPage.route(
      `**/api/integrations/strava/journals/${journal.id}/unmatched-athletes`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            data: [
              {
                id: '123',
                type: 'unmatched-strava-athlete',
                attributes: {
                  strava_athlete_id: 'test-athlete-123',
                  strava_athlete_name: 'Speedy Gonzales',
                },
              },
            ],
          }),
        });
      }
    );

    // 3. Navigate to journal detail page
    await authenticatedPage.goto(`/journals/${journal.id}`);

    // Wait for the page to load
    await expect(
      authenticatedPage.getByTestId('journal-title-field')
    ).toBeVisible();

    // 4. Verify unmatched athlete badge is shown
    const unmatchedBadge = authenticatedPage.getByText('Speedy Gonzales');
    await expect(unmatchedBadge).toBeVisible();

    // 5. Click the badge to open the "Link Participant" dialog
    await unmatchedBadge.click();

    // Verify dialog opens
    const dialog = authenticatedPage.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText('Link Strava Athlete')).toBeVisible();

    // 6. Search for the contact and link
    const searchInput = dialog.getByPlaceholder('Search contacts...');
    await searchInput.fill('Strava Runner');

    // Wait for search results
    const contactOption = dialog.getByText('Strava Runner');
    await expect(contactOption).toBeVisible();

    // Select the contact
    await contactOption.click();

    // The dialog should close, and the mapping API request should have fired.
    // Wait for the success toast
    await expect(authenticatedPage.getByText('Participant mapped successfully')).toBeVisible();

    // The unmatched athlete API will be re-fetched. Since we don't clear the mock,
    // the UI might still show it because our mock is static. That's fine, we move on to settings.

    // 7. Navigate to settings -> Integrations
    await authenticatedPage.goto('/settings');

    // Click Integrations tab
    await authenticatedPage.getByRole('tab', { name: 'Integrations' }).click();

    // Open Strava settings
    // Wait for integration list to load
    const stravaCard = authenticatedPage.getByText('Strava', { exact: true }).locator('..').locator('..');
    // Click the Settings button on the Strava integration card
    const stravaSettingsBtn = stravaCard.getByRole('button', { name: 'Settings' });
    await expect(stravaSettingsBtn).toBeVisible();
    await stravaSettingsBtn.click();

    // 8. Verify mapping is displayed in the Strava Athlete Mappings panel
    const settingsDialog = authenticatedPage.getByRole('dialog');
    await expect(settingsDialog).toBeVisible();
    await expect(settingsDialog.getByText('Athlete Mappings')).toBeVisible();

    // Check if the mapping appears in the table
    const athleteNameCell = settingsDialog.getByText('Speedy Gonzales');
    const athleteIdCell = settingsDialog.getByText('test-athlete-123');
    await expect(athleteNameCell).toBeVisible();
    await expect(athleteIdCell).toBeVisible();

    // 9. Delete the mapping
    const deleteBtn = settingsDialog.getByRole('button', { name: 'Delete mapping' });
    await deleteBtn.click();

    // Wait for success toast
    await expect(authenticatedPage.getByText('Mapping deleted successfully')).toBeVisible();

    // Verify mapping is removed from table
    await expect(athleteNameCell).not.toBeVisible();
  });
});
