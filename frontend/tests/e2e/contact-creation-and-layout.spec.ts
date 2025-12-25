/**
 * E2E tests for contact creation page and layout fixes.
 *
 * Tests verify:
 * 1. Contact creation page matches detail view layout
 * 2. Layout doesn't break when editing multiple name fields
 * 3. Add buttons are visible and functional
 */

import { test, expect } from './fixtures';

test.describe('Contact Creation Page', () => {
  test('should display contact creation page with consistent layout', async ({
    emptyContactsPage,
  }) => {
    await emptyContactsPage.goto('/contacts/new');

    // Verify page title and heading
    await expect(emptyContactsPage).toHaveTitle(/Personal Management System/);
    await expect(
      emptyContactsPage.getByRole('heading', { name: 'Add New Contact' })
    ).toBeVisible();

    // Verify the page has the same structure as detail view
    // Should have avatar placeholder
    const avatar = emptyContactsPage.locator('.h-32.w-32');
    await expect(avatar).toBeVisible();

    // Should have name fields in a card
    await expect(
      emptyContactsPage.getByRole('heading', { name: 'Contact Name' })
    ).toBeVisible();

    // Verify all name input fields are present
    await expect(
      emptyContactsPage.getByLabel('First Name', { exact: false })
    ).toBeVisible();
    await expect(
      emptyContactsPage.getByLabel('Last Name', { exact: true })
    ).toBeVisible();
    await expect(
      emptyContactsPage.getByLabel('Middle Name', { exact: true })
    ).toBeVisible();
    await expect(
      emptyContactsPage.getByLabel('Nickname', { exact: true })
    ).toBeVisible();
  });

  test('should create contact with minimal data', async ({
    emptyContactsPage,
  }) => {
    await emptyContactsPage.goto('/contacts/new');

    // Fill in only first name (required field)
    await emptyContactsPage
      .getByTestId('first-name-input')
      .fill('TestFirstName');

    // Save button should be enabled
    const saveButton = emptyContactsPage.getByRole('button', {
      name: /save contact/i,
    });
    await expect(saveButton).toBeEnabled();

    // Click save and wait for navigation
    await saveButton.click();

    // Should navigate to the contact detail page
    await expect(emptyContactsPage).toHaveURL(/\/contacts\/\d+$/);

    // Verify the contact was created with the correct name
    await expect(
      emptyContactsPage.locator('[data-testid="first-name-field"]')
    ).toContainText('TestFirstName');
  });

  test('should create contact with all name fields', async ({
    emptyContactsPage,
  }) => {
    await emptyContactsPage.goto('/contacts/new');

    // Fill in all name fields
    await emptyContactsPage.getByTestId('first-name-input').fill('John');
    await emptyContactsPage.getByTestId('last-name-input').fill('Doe');
    await emptyContactsPage.getByTestId('middle-name-input').fill('William');
    await emptyContactsPage.getByTestId('nickname-input').fill('Johnny');

    // Save the contact
    await emptyContactsPage
      .getByRole('button', { name: /save contact/i })
      .click();

    // Should navigate to detail page
    await expect(emptyContactsPage).toHaveURL(/\/contacts\/\d+$/);

    // Verify all fields are displayed correctly
    await expect(
      emptyContactsPage.locator('[data-testid="first-name-field"]')
    ).toContainText('John');
    await expect(
      emptyContactsPage.locator('[data-testid="last-name-field"]')
    ).toContainText('Doe');
    await expect(
      emptyContactsPage.locator('[data-testid="nickname-field"]')
    ).toContainText('Johnny');
  });

  test('should disable save button when first name is empty', async ({
    emptyContactsPage,
  }) => {
    await emptyContactsPage.goto('/contacts/new');

    // Save button should be disabled initially
    const saveButton = emptyContactsPage.getByRole('button', {
      name: /save contact/i,
    });
    await expect(saveButton).toBeDisabled();

    // Fill in first name
    await emptyContactsPage.getByTestId('first-name-input').fill('Test');

    // Save button should now be enabled
    await expect(saveButton).toBeEnabled();

    // Clear first name
    await emptyContactsPage.getByTestId('first-name-input').clear();

    // Save button should be disabled again
    await expect(saveButton).toBeDisabled();
  });

  test('should navigate back to contacts list on cancel', async ({
    emptyContactsPage,
  }) => {
    await emptyContactsPage.goto('/contacts/new');

    // Click cancel button
    await emptyContactsPage.getByRole('button', { name: /cancel/i }).click();

    // Should navigate back to contacts list
    await expect(emptyContactsPage).toHaveURL(/\/contacts$/);
  });

  test('should navigate back to contacts list via back button', async ({
    emptyContactsPage,
  }) => {
    await emptyContactsPage.goto('/contacts/new');

    // Click back to contacts button
    await emptyContactsPage
      .getByRole('button', { name: /back to contacts/i })
      .click();

    // Should navigate back to contacts list
    await expect(emptyContactsPage).toHaveURL(/\/contacts$/);
  });
});

test.describe('Contact Detail Page Layout', () => {
  test('should not break layout when editing both first and last name simultaneously', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    // Click on first name to enter edit mode
    const firstNameField = page.locator('[data-testid="first-name-field"]');
    await firstNameField.click();

    // Click on last name to enter edit mode (both should be in edit mode now)
    const lastNameField = page.locator('[data-testid="last-name-field"]');
    await lastNameField.click();

    // Verify both input fields are visible
    const firstNameInput = page.locator(
      '[data-testid="first-name-field"] input'
    );
    const lastNameInput = page.locator('[data-testid="last-name-field"] input');

    await expect(firstNameInput).toBeVisible();
    await expect(lastNameInput).toBeVisible();

    // Verify the layout is not broken - check that the fields are within viewport
    const firstNameBox = await firstNameInput.boundingBox();
    const lastNameBox = await lastNameInput.boundingBox();

    expect(firstNameBox).toBeTruthy();
    expect(lastNameBox).toBeTruthy();

    // Both fields should be visible in the viewport
    if (firstNameBox && lastNameBox) {
      const viewportSize = page.viewportSize();
      expect(viewportSize).toBeTruthy();

      if (viewportSize) {
        // Fields should not overflow the viewport
        expect(firstNameBox.x + firstNameBox.width).toBeLessThanOrEqual(
          viewportSize.width
        );
        expect(lastNameBox.x + lastNameBox.width).toBeLessThanOrEqual(
          viewportSize.width
        );
      }
    }
  });

  test('should maintain proper spacing between sections', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    // Get the header section
    const header = page.locator('header').first();
    await expect(header).toBeVisible();

    // Get the contact methods section (first section after header)
    const contactMethodsHeading = page.getByRole('heading', {
      name: /contact methods/i,
    });
    await expect(contactMethodsHeading).toBeVisible();

    // Verify there's reasonable spacing (not excessive)
    const headerBox = await header.boundingBox();
    const detailsBox = await contactMethodsHeading.boundingBox();

    if (headerBox && detailsBox) {
      const spacing = detailsBox.y - (headerBox.y + headerBox.height);
      // Spacing should be reasonable (between 16px and 64px)
      expect(spacing).toBeGreaterThanOrEqual(16);
      expect(spacing).toBeLessThanOrEqual(64);
    }
  });
});

test.describe('Add Buttons Visibility', () => {
  test('should display Add button for contact methods with text label', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    // Find the Contact Methods section
    const contactMethodsHeading = page.getByRole('heading', {
      name: /contact methods/i,
    });
    await expect(contactMethodsHeading).toBeVisible();

    // Find the Add button - it should have both icon and text
    const addButton = page.getByRole('button', { name: /add/i }).first();
    await expect(addButton).toBeVisible();

    // Verify the button contains the text "Add"
    await expect(addButton).toContainText('Add');
  });

  test('should display Add button for addresses with text label', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    // Find the Addresses section
    const addressesHeading = page.getByRole('heading', {
      name: /addresses/i,
    });
    await expect(addressesHeading).toBeVisible();

    // Find the Add button in the addresses section
    const addButton = page
      .locator('[data-testid="contact-addresses-list"]')
      .getByRole('button', { name: /add/i });
    await expect(addButton).toBeVisible();

    // Verify the button contains the text "Add"
    await expect(addButton).toContainText('Add');
  });

  test('should be able to click Add button to add contact method', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    // Click the Add button in Contact Methods section
    const addButton = page
      .locator('text=Contact Methods')
      .locator('..')
      .locator('..')
      .getByRole('button', { name: /add/i });

    await addButton.click();

    // Should show the add form
    await expect(page.getByLabel(/type/i)).toBeVisible();
    await expect(page.getByTestId('method-value-input')).toBeVisible();
  });

  test('should be able to click Add button to add address', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);

    // Click the Add button in Addresses section
    const addButton = page
      .locator('text=Addresses')
      .locator('..')
      .locator('..')
      .getByRole('button', { name: /add/i });

    await addButton.click();

    // Should show the add form - use testid to avoid ambiguity with multiple street fields
    await expect(page.getByTestId('address-street-input')).toBeVisible();
  });
});
