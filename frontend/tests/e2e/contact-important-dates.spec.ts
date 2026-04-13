import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

test.describe('Important Dates (API Surface Verification)', () => {
  test('should not crash when viewing a contact with important dates in the API response', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);

    // Create a contact with important dates (supported by updated DataManager)
    const contacts = await dataManager.createContacts([
      {
        firstName: 'API',
        lastName: 'ImportantDates',
        importantDates: [
          {
            date_type: 'birthday',
            precision: 'full',
            year: 1985,
            month: 10,
            day: 25,
          },
          {
            date_type: 'work_anniversary',
            precision: 'year',
            year: 2020,
          },
        ],
      },
      {
        firstName: 'No',
        lastName: 'ImportantDates',
      },
    ]);

    testCleanup(async () => await dataManager.cleanup());

    const contactWithDates = contacts[0];

    // Navigate to the contact list page
    await authenticatedPage.goto('/contacts');

    // Ensure the page loaded successfully
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Contacts' })
    ).toBeVisible();

    // Verify contact appears in the list
    await expect(
      authenticatedPage
        .locator(
          `text=${contactWithDates.firstName} ${contactWithDates.lastName}`
        )
        .first()
    ).toBeVisible();

    // Navigate to the contact detail page
    await authenticatedPage.goto(`/contacts/${contactWithDates.id}`);

    // Verify contact detail page loads without crashing when API returns important_dates
    await expect(
      authenticatedPage
        .locator(
          `text=${contactWithDates.firstName} ${contactWithDates.lastName}`
        )
        .first()
    ).toBeVisible();

    // We expect the UI to not break, even though important dates are not yet rendered in the UI layer
    const pageContent = await authenticatedPage.content();
    expect(
      pageContent.includes('Application Error') ||
        pageContent.includes('Uncaught exception')
    ).toBeFalsy();
  });
});
