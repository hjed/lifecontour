import { test, expect } from './fixtures';
import type { Page } from '@playwright/test';

test.describe('Contact Inline Editing', () => {
  /**
   * Helper function to wait for and verify a field update API request
   */
  async function waitForFieldUpdateRequest(
    page: Page,
    contactId: string,
    fieldName: string,
    expectedValue: string
  ) {
    const requestPromise = page.waitForRequest(
      req =>
        req.url().includes(`/api/contacts/${contactId}/fields/${fieldName}`) &&
        req.method() === 'PATCH',
      { timeout: 10000 }
    );

    const apiRequest = await requestPromise;
    const requestBody = apiRequest.postDataJSON();

    // Verify request format matches backend expectations
    expect(requestBody).toHaveProperty('data');
    expect(requestBody.data).toHaveProperty('type', 'contact_fields');
    expect(requestBody.data).toHaveProperty('attributes');
    expect(requestBody.data.attributes).toHaveProperty('value', expectedValue);
  }

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

  test('should edit contact first name inline and save with correct API call', async ({
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

    // Set up request interception and press Enter
    const verifyRequest = waitForFieldUpdateRequest(
      page,
      contact.id,
      'first_name',
      'UpdatedFirstName'
    );
    await input.press('Enter');
    await verifyRequest;

    // Wait for the UI to update
    await page.waitForLoadState('networkidle');
    await expect(firstNameField).toContainText('UpdatedFirstName');
  });

  test('should edit contact last name inline and save with correct API call', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    const lastNameField = page.locator('[data-testid="last-name-field"]');
    await lastNameField.click();

    const input = page.locator('[data-testid="last-name-field"] input');
    await input.clear();
    await input.fill('UpdatedLastName');

    // Set up request interception and press Enter
    const verifyRequest = waitForFieldUpdateRequest(
      page,
      contact.id,
      'last_name',
      'UpdatedLastName'
    );
    await input.press('Enter');
    await verifyRequest;

    await page.waitForLoadState('networkidle');
    await expect(lastNameField).toContainText('UpdatedLastName');
  });

  test('should edit contact nickname inline and save with correct API call', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    const nicknameField = page.locator('[data-testid="nickname-field"]');

    // Scroll the element into view
    await nicknameField.scrollIntoViewIfNeeded();

    // Wait for the element to be visible and clickable
    await expect(nicknameField).toBeVisible();
    await nicknameField.click();

    const input = page.locator('[data-testid="nickname-field"] input');
    await input.clear();
    await input.fill('UpdatedNickname');

    // Set up request interception and press Enter
    const verifyRequest = waitForFieldUpdateRequest(
      page,
      contact.id,
      'nick_name',
      'UpdatedNickname'
    );
    await input.press('Enter');
    await verifyRequest;

    await page.waitForLoadState('networkidle');
    await expect(nicknameField).toContainText('UpdatedNickname');
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
