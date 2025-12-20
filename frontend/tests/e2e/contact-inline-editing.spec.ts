import { test, expect } from './fixtures';

test.describe('Contact Inline Editing', () => {
  test('should display contact detail page', async ({ contactsWithData }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);
    // Wait for the page to load and verify we're on the contact detail page
    await expect(
      page.locator('[data-testid="first-name-field"]')
    ).toBeVisible();
  });

  test('should enter edit mode when clicking on first name field', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    const firstNameField = page.locator('[data-testid="first-name-field"]');
    await firstNameField.click();

    const input = page.locator('[data-testid="first-name-field"] input');
    await expect(input).toBeVisible();
  });

  test('should cancel inline edit with Escape key', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    const firstNameField = page.locator('[data-testid="first-name-field"]');
    await firstNameField.click();

    await page.keyboard.press('Escape');

    const input = page.locator('[data-testid="first-name-field"] input');
    await expect(input).not.toBeVisible();
  });

  test('should edit contact first name inline and save', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    const firstNameField = page.locator('[data-testid="first-name-field"]');
    await firstNameField.click();

    const input = page.locator('[data-testid="first-name-field"] input');
    await input.clear();
    await input.fill('UpdatedFirstName');

    await page.keyboard.press('Enter');
    await page.waitForTimeout(500);

    await expect(firstNameField).toContainText('UpdatedFirstName');
  });

  test('should display contact methods section', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    const contactMethodsHeading = page.getByRole('heading', {
      name: 'Contact Methods',
    });
    await expect(contactMethodsHeading).toBeVisible();

    const addMethodButton = page.getByRole('button', {
      name: /add contact method/i,
    });
    await expect(addMethodButton).toBeVisible();
  });

  test('should display addresses section', async ({ contactsWithData }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    const addressesHeading = page.getByRole('heading', { name: 'Addresses' });
    await expect(addressesHeading).toBeVisible();

    const addAddressButton = page.getByRole('button', { name: /add address/i });
    await expect(addAddressButton).toBeVisible();
  });

  test('should display activity feed section', async ({ contactsWithData }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    const activityHeading = page.getByRole('heading', {
      name: /activity|timeline/i,
    });
    await expect(activityHeading).toBeVisible();
  });

  test('should display relationships section', async ({ contactsWithData }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[1];

    await page.goto(`/contacts/${contact.id}`);

    const relationshipsHeading = page.getByRole('heading', {
      name: /relationships/i,
    });
    await expect(relationshipsHeading).toBeVisible();
  });
});
