/**
 * E2E tests for contact inline editing workflows.
 * Tests complete editing workflows for contact identity, methods, and addresses.
 */

import { test, expect } from './fixtures';

test.describe('Contact Inline Editing - Complete Workflows', () => {
  test('should display contact detail page with inline editable fields', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    // Navigate to contact detail page
    await page.goto(`/contacts/${contact.id}`);
    await expect(page).toHaveURL(new RegExp(`/contacts/${contact.id}`));

    // Verify inline editable fields are visible
    const firstNameField = page.locator('[data-testid="first-name-field"]');
    await expect(firstNameField).toBeVisible();

    const lastNameField = page.locator('[data-testid="last-name-field"]');
    await expect(lastNameField).toBeVisible();

    // Verify contact methods section is visible
    const contactMethodsSection = page.locator('text=Contact Methods');
    await expect(contactMethodsSection).toBeVisible();

    // Verify addresses section is visible
    const addressesSection = page.locator('text=Addresses');
    await expect(addressesSection).toBeVisible();
  });

  test('should enter edit mode when clicking on first name field', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    // Find and click the first name field to edit
    const firstNameField = page.locator('[data-testid="first-name-field"]');
    await expect(firstNameField).toBeVisible();
    await firstNameField.click();

    // Should show edit input
    const firstNameInput = page.locator(
      '[data-testid="first-name-field-input"]'
    );
    await expect(firstNameInput).toBeVisible();
  });

  test('should cancel inline edit with Escape key', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];
    const originalFirstName = contact.firstName;

    await page.goto(`/contacts/${contact.id}`);

    const firstNameField = page.locator('[data-testid="first-name-field"]');
    await firstNameField.click();

    const firstNameInput = page.locator(
      '[data-testid="first-name-field-input"]'
    );
    await expect(firstNameInput).toBeVisible();

    // Press Escape to cancel
    await firstNameInput.press('Escape');

    // Should revert to view mode
    await expect(firstNameField).toBeVisible();
  });

  test('should edit contact first name inline and save', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    // Find and click the first name field to edit
    const firstNameField = page.locator('[data-testid="first-name-field"]');
    await expect(firstNameField).toBeVisible();
    await firstNameField.click();

    // Should show edit input
    const firstNameInput = page.locator(
      '[data-testid="first-name-field-input"]'
    );
    await expect(firstNameInput).toBeVisible();

    // Clear and type new value
    await firstNameInput.clear();
    await firstNameInput.fill('UpdatedFirstName');

    // Submit by pressing Enter
    await firstNameInput.press('Enter');

    // Should show updated value
    await expect(firstNameField).toContainText('UpdatedFirstName');
  });

  test('should edit contact last name inline and save', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    const lastNameField = page.locator('[data-testid="last-name-field"]');
    await expect(lastNameField).toBeVisible();
    await lastNameField.click();

    const lastNameInput = page.locator('[data-testid="last-name-field-input"]');
    await expect(lastNameInput).toBeVisible();

    await lastNameInput.clear();
    await lastNameInput.fill('UpdatedLastName');
    await lastNameInput.press('Enter');

    await expect(lastNameField).toContainText('UpdatedLastName');
  });

  test('should display contact methods section with add button', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    // Verify contact methods section
    const contactMethodsSection = page.locator('text=Contact Methods');
    await expect(contactMethodsSection).toBeVisible();

    // Verify add button is visible
    const addMethodButton = page.locator(
      'button:has-text("Add Contact Method")'
    );
    await expect(addMethodButton).toBeVisible();
  });

  test('should add new contact method', async ({ contactsWithData }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    // Find and click "Add Contact Method" button
    const addMethodButton = page.locator(
      'button:has-text("Add Contact Method")'
    );
    await expect(addMethodButton).toBeVisible();
    await addMethodButton.click();

    // Should show form
    const methodTypeSelect = page.locator('[data-testid="method-type-select"]');
    await expect(methodTypeSelect).toBeVisible();

    // Select email type
    await methodTypeSelect.selectOption('email');

    // Fill email
    const emailInput = page.locator('[data-testid="method-value-input"]');
    await emailInput.fill('newemail@example.com');

    // Submit
    const submitButton = page.locator('button:has-text("Add")').last();
    await submitButton.click();

    // Should show new method in list
    await expect(page.locator('text=newemail@example.com')).toBeVisible();
  });

  test('should display addresses section with add button', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    // Verify addresses section
    const addressesSection = page.locator('text=Addresses');
    await expect(addressesSection).toBeVisible();

    // Verify add button is visible
    const addAddressButton = page.locator('button:has-text("Add Address")');
    await expect(addAddressButton).toBeVisible();
  });

  test('should add new address', async ({ contactsWithData }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    // Find and click "Add Address" button
    const addAddressButton = page.locator('button:has-text("Add Address")');
    await expect(addAddressButton).toBeVisible();
    await addAddressButton.click();

    // Should show form
    const streetInput = page.locator('[data-testid="address-street-input"]');
    await expect(streetInput).toBeVisible();

    // Fill address fields
    await streetInput.fill('123 New Street');
    await page.locator('[data-testid="address-suburb-input"]').fill('Sydney');
    await page.locator('[data-testid="address-state-input"]').fill('NSW');
    await page.locator('[data-testid="address-postcode-input"]').fill('2000');

    // Submit
    const submitButton = page.locator('button:has-text("Add")').last();
    await submitButton.click();

    // Should show new address in list
    await expect(page.locator('text=123 New Street')).toBeVisible();
  });

  test('should display activity feed section', async ({ contactsWithData }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    // Verify activity feed section is visible
    const activityFeedHeading = page.getByRole('heading', {
      name: /Activity/i,
    });
    await expect(activityFeedHeading).toBeVisible({ timeout: 10000 });
  });

  test('should display relationships section', async ({ contactsWithData }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    // Verify relationships section is visible
    const relationshipsHeading = page.getByRole('heading', {
      name: /Relationships/i,
    });
    await expect(relationshipsHeading).toBeVisible();
  });
});
