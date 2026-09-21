import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';
import { selectRadixOption } from './utils/radix-select';

test.describe('Important Dates', () => {
  test('should display, edit, add, and delete important dates', async ({
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

    // --- Edit the existing birthday ---
    // The pencil opens the inline editor in place, prefilled from the row.
    await authenticatedPage.getByLabel('Edit birthday').click();
    await expect(authenticatedPage.getByPlaceholder('YYYY')).toHaveValue(
      '1985'
    );

    await authenticatedPage.getByPlaceholder('YYYY').fill('1986');

    // The card writes to the date's own endpoint now, not the whole-contact PUT.
    const editResponsePromise = authenticatedPage.waitForResponse(
      response =>
        /\/api\/contacts\/\d+\/important-dates\/\d+$/.test(response.url()) &&
        response.request().method() === 'PUT' &&
        response.status() === 200
    );

    await authenticatedPage.getByLabel('Save date').click();
    await editResponsePromise;

    // The edited value replaces the old one on the same row.
    await expect(authenticatedPage.getByText('1986')).toBeVisible({
      timeout: 15000,
    });
    await expect(authenticatedPage.getByText('1985')).toBeHidden();

    // --- Add a new Important Date ---
    await authenticatedPage.getByLabel('Add important date').click();

    // Choose the type and precision by typeahead; see selectRadixOption for
    // why the portaled options are never clicked.
    await selectRadixOption(
      authenticatedPage,
      authenticatedPage.getByRole('combobox', { name: 'Important Date Type' }),
      'Marriage Ann.'
    );
    await selectRadixOption(
      authenticatedPage,
      authenticatedPage.getByRole('combobox', {
        name: 'Important Date Precision',
      }),
      'Year Only'
    );

    // Enter Year
    await authenticatedPage.getByPlaceholder('YYYY').fill('2010');

    // Wait for the POST that creates the new date
    const saveResponsePromise = authenticatedPage.waitForResponse(
      response =>
        /\/api\/contacts\/\d+\/important-dates$/.test(response.url()) &&
        response.request().method() === 'POST' &&
        response.status() === 201
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

    // Wait for the DELETE of that one date
    const deleteResponsePromise = authenticatedPage.waitForResponse(
      response =>
        /\/api\/contacts\/\d+\/important-dates\/\d+$/.test(response.url()) &&
        response.request().method() === 'DELETE' &&
        response.status() === 204
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
