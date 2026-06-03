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
    await expect(async () => {
      await authenticatedPage
        .getByRole('combobox', { name: 'Important Date Type' })
        .click();
      const typeOption = authenticatedPage.getByRole('option', {
        name: 'Marriage Ann.',
      });
      await expect(typeOption).toBeVisible({ timeout: 1000 });
      await typeOption.click({ force: true });
      await expect(
        authenticatedPage.getByRole('combobox', { name: 'Important Date Type' })
      ).toHaveText('Marriage Ann.', { timeout: 1000 });
    }).toPass({ timeout: 10000 });

    // Select Precision: YEAR
    await expect(async () => {
      await authenticatedPage
        .getByRole('combobox', { name: 'Important Date Precision' })
        .click();
      const precisionOption = authenticatedPage.getByRole('option', {
        name: 'Year Only',
      });
      await expect(precisionOption).toBeVisible({ timeout: 1000 });
      await precisionOption.click({ force: true });
      await expect(
        authenticatedPage.getByRole('combobox', {
          name: 'Important Date Precision',
        })
      ).toHaveText('Year Only', { timeout: 1000 });
    }).toPass({ timeout: 10000 });

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

    // Verify UI updates without needing polling/reload loops
    await expect(
      authenticatedPage.getByText(/marriage anniversary/i)
    ).toBeVisible({ timeout: 15000 });
    await expect(authenticatedPage.getByText('2010')).toBeVisible({
      timeout: 15000,
    });

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
    await expect(deleteDialog).toBeHidden();
    await expect(authenticatedPage.getByText(/birthday/i)).not.toBeVisible({
      timeout: 15000,
    });
    // But marriage anniversary is still there
    await expect(
      authenticatedPage.getByText(/marriage anniversary/i)
    ).toBeVisible({ timeout: 15000 });
  });

  test('should render synced dates at different precisions', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);

    // Create contact with dates at different precisions
    // This simulates what a Google-synced contact would look like
    const contacts = await dataManager.createContacts([
      {
        firstName: 'Synced',
        lastName: 'Dates',
        importantDates: [
          {
            // Birthday with full precision (year, month, day)
            date_type: 'birthday',
            precision: 'full',
            year: 1990,
            month: 5,
            day: 20,
          },
          {
            // Marriage anniversary with day_month precision (no year)
            date_type: 'marriage_anniversary',
            precision: 'day_month',
            month: 6,
            day: 15,
          },
        ],
      },
    ]);

    testCleanup(async () => await dataManager.cleanup());
    const contact = contacts[0];

    // Navigate to the contact detail page
    await authenticatedPage.goto(`/contacts/${contact.id}`);

    // Wait for page to load
    await expect(
      authenticatedPage
        .locator(`text=${contact.firstName} ${contact.lastName}`)
        .first()
    ).toBeVisible();

    // Verify Important Dates section renders
    await expect(authenticatedPage.getByText('Important Dates')).toBeVisible();

    // Verify birthday with full precision renders
    await expect(authenticatedPage.getByText(/birthday/i)).toBeVisible();
    await expect(authenticatedPage.getByText('1990')).toBeVisible();

    // Verify marriage anniversary renders
    await expect(
      authenticatedPage.getByText(/marriage anniversary/i)
    ).toBeVisible();

    // Verify both date types are actually rendered
    // If test IDs don't exist, fall back to checking both types are visible
    const birthdayVisible = authenticatedPage.getByText(/birthday/i);
    const anniversaryVisible =
      authenticatedPage.getByText(/marriage anniversary/i);
    await expect(birthdayVisible).toBeVisible();
    await expect(anniversaryVisible).toBeVisible();
  });
});
