import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

test.describe('Important Dates', () => {
  test('should display, add, and delete important dates', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);

    // Create a contact with important dates
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
        ],
      },
    ]);

    testCleanup(async () => await dataManager.cleanup());
    const contactWithDates = contacts[0];

    // Navigate to the contact detail page directly
    await authenticatedPage.goto(`/contacts/${contactWithDates.id}`);

    // Wait for page to load
    await expect(
      authenticatedPage
        .locator(
          `text=${contactWithDates.firstName} ${contactWithDates.lastName}`
        )
        .first()
    ).toBeVisible();

    // Verify Important Dates section renders
    await expect(authenticatedPage.getByText('Important Dates')).toBeVisible();

    // Verify existing birthday renders with its formatted text
    await expect(authenticatedPage.getByText(/birthday/i)).toBeVisible();
    await expect(authenticatedPage.getByText('1985')).toBeVisible();

    // --- Add a new Important Date ---
    await authenticatedPage.getByLabel('Add important date').click();

    // Select ANNIVERSARY_MARK (or any other built-in type)
    // The type select uses a button under the hood in shadcn/ui select
    await authenticatedPage
      .getByRole('combobox', { name: 'Important Date Type' })
      .click();
    await authenticatedPage
      .getByRole('option', { name: 'Marriage Ann.' })
      .click();

    // Select Precision: YEAR
    await authenticatedPage
      .getByRole('combobox', { name: 'Important Date Precision' })
      .click();
    await authenticatedPage.getByRole('option', { name: 'Year Only' }).click();

    // Enter Year
    await authenticatedPage.getByPlaceholder('YYYY').fill('2010');

    // Wait for the PUT request for the new date
    const saveResponsePromise = authenticatedPage.waitForResponse(
      response =>
        response.url().includes('/api/contacts/') &&
        response.request().method() === 'PUT' &&
        response.status() === 200
    );

    // Save
    await authenticatedPage.getByLabel('Save date').click();
    await saveResponsePromise;

    // Verify UI updates
    await expect(
      authenticatedPage.getByText(/marriage anniversary/i)
    ).toBeVisible({ timeout: 10000 });
    await expect(authenticatedPage.getByText('2010')).toBeVisible();

    // --- Delete the birthday ---
    await authenticatedPage.getByLabel('Delete birthday').click();

    // Wait for the confirm dialog
    const deleteDialog = authenticatedPage.getByRole('dialog');
    await expect(deleteDialog).toBeVisible();

    // Wait for the PUT request for the deletion
    const deleteResponsePromise = authenticatedPage.waitForResponse(
      response =>
        response.url().includes('/api/contacts/') &&
        response.request().method() === 'PUT' &&
        response.status() === 200
    );

    // Confirm delete
    await deleteDialog.getByRole('button', { name: 'Delete' }).click();
    await deleteResponsePromise;

    // Verify dialog is closed and birthday is removed
    await expect(deleteDialog).not.toBeVisible();
    await expect(authenticatedPage.getByText(/birthday/i)).not.toBeVisible({
      timeout: 10000,
    });
    // But marriage anniversary is still there
    await expect(
      authenticatedPage.getByText(/marriage anniversary/i)
    ).toBeVisible();
  });
});
