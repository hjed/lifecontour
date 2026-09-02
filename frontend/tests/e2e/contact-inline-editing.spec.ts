import { test, expect } from './fixtures';
import type { Page } from '@playwright/test';

/**
 * Helper function to wait for and verify a field update API request
 */
async function waitForFieldUpdateRequest(
  page: Page,
  contactId: string,
  fieldName: string,
  expectedValue: string
) {
  // Wait for the response so we know the server finished processing
  const responsePromise = page.waitForResponse(
    res =>
      res
        .request()
        .url()
        .includes(`/api/contacts/${contactId}/fields/${fieldName}`) &&
      res.request().method() === 'PATCH' &&
      res.status() === 200,
    { timeout: 15000 }
  );

  const response = await responsePromise;
  const requestBody = response.request().postDataJSON();

  // Verify request format matches backend expectations
  expect(requestBody).toHaveProperty('data');
  expect(requestBody.data).toHaveProperty('type', 'contact_fields');
  expect(requestBody.data).toHaveProperty('attributes');
  expect(requestBody.data.attributes).toHaveProperty('value', expectedValue);
}

// Note: inline-edit view/edit-mode toggling, click-to-edit, and Escape-to-cancel
// are unit-tested in InlineEditField.test.tsx / InlineEditEmailField.test.tsx.
// These e2e tests cover only the real PATCH /api/contacts/{id}/fields/{field}
// save contract that the component tests mock out.
test.describe('Contact Inline Editing', () => {
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

    // Wait for the UI to update (element-based wait instead of networkidle)
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

    // Wait for the UI to update (element-based wait instead of networkidle)
    await expect(lastNameField).toContainText('UpdatedLastName');
  });

  test('should edit contact nickname inline and save with correct API call', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    const nicknameField = page.locator('[data-testid="nickname-field"]');

    // Enter edit mode
    // Standard click ensures actionability checks (visibility, stable, receiving events)
    await expect(nicknameField).toBeVisible();
    await nicknameField.click();

    const input = page.locator('[data-testid="nickname-field"] input');
    await expect(input).toBeVisible();
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

    // Wait for the UI to update (element-based wait instead of networkidle)
    await expect(nicknameField).toContainText('UpdatedNickname');
  });

  // Each section's own rendering (headings, add buttons, empty states) is
  // unit-tested in ContactMethodsList.test.tsx, ContactAddressesList.test.tsx,
  // ActivityFeed.test.tsx, and RelationshipsList.test.tsx. What only e2e can
  // catch is a section dropping out of the detail page's composition — so one
  // page load asserts all four are mounted, replacing the four separate
  // display tests (and their four page loads) that stood here.
  test('mounts all detail page sections', async ({ contactsWithData }) => {
    const { page, contacts } = contactsWithData;

    await page.goto(`/contacts/${contacts[0].id}`);

    await expect(
      page.getByRole('heading', { name: 'Contact Methods' })
    ).toBeVisible();
    await expect(
      page.getByRole('heading', { name: 'Addresses' })
    ).toBeVisible();
    await expect(
      page.getByRole('heading', { name: /activity|timeline/i })
    ).toBeVisible();
    await expect(
      page.getByRole('heading', { name: /relationships/i })
    ).toBeVisible();
  });
});
