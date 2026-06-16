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
    // Select the relationship type via keyboard typeahead rather than clicking
    // the option. On mobile, clicking the portaled Radix Select item is
    // unreliable — Playwright mis-computes the option's bounding box, so even
    // force-clicks miss it and the value never commits (leaving the submit
    // button disabled). Typing matches by text and avoids coordinates entirely.
    // Wrap in toPass() to absorb a dropped keystroke while the dropdown is still
    // opening, retrying until the trigger reflects the chosen value.
    await expect(async () => {
      // Close any stale/half-open dropdown from a prior attempt, then open fresh.
      await page.keyboard.press('Escape');
      await typeTrigger.click();
      await expect(page.getByRole('listbox')).toBeVisible();
      await page.keyboard.type('Friend', { delay: 50 });
      await page.keyboard.press('Enter');
      // Confirm the value committed. Short timeout so a dropped keystroke
      // retries instead of consuming the global 15s expect budget on one pass.
      await expect(typeTrigger).toContainText('Friend', { timeout: 3000 });
    }).toPass({ timeout: 15000 });

    // Submit
    const addButton = formContainer.getByRole('button', {
      name: 'Add Relationship',
    });
    await expect(addButton).toBeEnabled();

    // Register both response waiters BEFORE clicking. The successful POST
    // triggers a React Query cache invalidation that refetches the contact via
    // GET; if that GET listener is only registered after awaiting the POST, the
    // refetch can fire first and the wait times out (the chromium flake). Start
    // listening up front so neither response can be missed.
    const postResponse = page.waitForResponse(
      resp =>
        resp.url().includes('/relationships') &&
        resp.request().method() === 'POST' &&
        resp.ok()
    );
    const getResponse = page.waitForResponse(
      resp =>
        resp.url().includes('/api/contacts/') &&
        resp.request().method() === 'GET' &&
        resp.ok()
    );
    await addButton.click();
    await postResponse;
    await getResponse;

    // Wait for the relationship to appear in the list with "You" label
    await expect(page.getByTestId('relationship-user-target')).toBeVisible({
      timeout: 15000,
    });
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
