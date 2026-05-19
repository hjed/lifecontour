/**
 * E2E Tests for Contact Relationships
 */

import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';
import type { Page } from '@playwright/test';

function attachClientErrorLogging(page: Page): void {
  page.on('pageerror', err => {
    console.error('[pageerror]', err);
  });
  page.on('console', msg => {
    if (msg.type() === 'error') {
      console.error('[console:error]', msg.text());
    }
  });
}

test.describe('Contact Relationships', () => {
  test.beforeEach(async ({ authenticatedPage }) => {
    attachClientErrorLogging(authenticatedPage);
  });

  test('should display relationship type options when adding a relationship', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    // Create a primary contact
    const contact = await dataManager.createContact({
      firstName: 'Primary',
      lastName: 'Contact',
      email: 'primary@example.com',
    });

    // Navigate to primary contact detail page
    await page.goto(`/contacts/${contact.id}`);

    // Wait for the page to load
    await expect(
      page.getByText(`${contact.firstName} ${contact.lastName}`)
    ).toBeVisible();

    // The relationships section should be visible
    await expect(
      page.getByRole('heading', { name: 'Relationships' })
    ).toBeVisible();

    // Click Add Relationship
    await page.getByRole('button', { name: 'Add Relationship' }).click();

    const formContainer = page
      .locator('div.bg-card')
      .filter({
        has: page.getByRole('heading', { name: 'Add New Relationship' }),
      })
      .first();
    const typeTrigger = formContainer
      .locator('.space-y-2')
      .filter({ hasText: 'Relationship Type' })
      .getByRole('combobox');
    await typeTrigger.click();

    // Verify that relationship types are loaded ("Parent", "Child", etc)
    // We expect at least these options to be in the listbox.
    const listbox = page.getByRole('listbox');
    await expect(
      listbox.getByRole('option', { name: 'Parent', exact: true })
    ).toBeVisible();
    await expect(
      listbox.getByRole('option', { name: 'Child', exact: true })
    ).toBeVisible();
    await expect(
      listbox.getByRole('option', { name: 'Partner', exact: true })
    ).toBeVisible();

    // Select the first option
    const parentOption = listbox.getByRole('option', {
      name: 'Parent',
      exact: true,
    });
    await expect(parentOption).toBeVisible();
    // Use force: true to bypass Playwright mobile bounding box bug on Radix Select portals
    await parentOption.click({ force: true });
  });

  test('should toggle "Relationship with me" and create a user-targeted relationship', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    // Create a contact
    const contact = await dataManager.createContact({
      firstName: 'UserRel',
      lastName: 'Test',
      email: 'userrel@example.com',
    });

    // Navigate to contact detail page
    await page.goto(`/contacts/${contact.id}`);
    await expect(
      page.getByText(`${contact.firstName} ${contact.lastName}`)
    ).toBeVisible();

    // Click Add Relationship
    await page.getByRole('button', { name: 'Add Relationship' }).click();

    // Verify the form appears
    await expect(
      page.getByRole('heading', { name: 'Add New Relationship' })
    ).toBeVisible();

    // Toggle "Relationship with me"
    const toggle = page.getByRole('switch', {
      name: 'Toggle relationship target to yourself',
    });
    await expect(toggle).toBeVisible();
    await toggle.click();

    // Contact search should be hidden and "you" indicator should appear
    await expect(
      page.getByText('This relationship will be between this contact and')
    ).toBeVisible();
    await expect(page.getByPlaceholder('Search for a contact...')).toBeHidden();

    // Select relationship type
    const formContainer = page
      .locator('div.bg-card')
      .filter({
        has: page.getByRole('heading', { name: 'Add New Relationship' }),
      })
      .first();
    const typeTrigger = formContainer
      .locator('.space-y-2')
      .filter({ hasText: 'Relationship Type' })
      .getByRole('combobox');
    await typeTrigger.click();
    const option = page
      .getByRole('listbox')
      .getByRole('option', { name: 'Friend', exact: true });
    await expect(option).toBeVisible();
    // Use force: true to bypass Playwright mobile bounding box bug on Radix Select portals
    await option.click({ force: true });

    // Submit
    const addButton = formContainer.getByRole('button', {
      name: 'Add Relationship',
    });
    await expect(addButton).toBeEnabled();

    // Wait for the API response
    const responsePromise = page.waitForResponse(
      resp =>
        resp.url().includes('/relationships') &&
        resp.request().method() === 'POST'
    );
    await addButton.click();
    await responsePromise;

    // Wait for the relationship to appear in the list with "You" label
    await expect(page.getByTestId('relationship-user-target')).toBeVisible();
    await expect(page.getByTestId('relationship-user-target')).toHaveText(
      'You'
    );
  });

  test('should display "You" for existing user-targeted relationships', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    // Create a contact
    const contact = await dataManager.createContact({
      firstName: 'DisplayYou',
      lastName: 'Test',
      email: 'displayyou@example.com',
    });

    // Create a user-targeted relationship via the API
    await dataManager.createUserRelationship(contact.id, 'partner');

    // Navigate to contact detail page
    await page.goto(`/contacts/${contact.id}`);
    await expect(
      page.getByText(`${contact.firstName} ${contact.lastName}`)
    ).toBeVisible();

    // Verify "You" is displayed in the relationships list
    await expect(page.getByTestId('relationship-user-target')).toBeVisible();
    await expect(page.getByTestId('relationship-user-target')).toHaveText(
      'You'
    );

    // "You" should NOT be rendered as a link
    const youElement = page.getByTestId('relationship-user-target');
    const tagName = await youElement.evaluate(el => el.tagName.toLowerCase());
    expect(tagName).toBe('span');
  });
});
