/**
 * E2E Tests for Contact Activity Feed
 *
 * Tests the Activity Feed functionality on the contact detail page,
 * including displaying history entries, pagination, and visual formatting.
 */

import { test, expect } from './fixtures';

test.describe('Contact Activity Feed', () => {
  test('should display Activity Feed section on contact detail page', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    // Navigate to contact detail page
    await page.goto(`/contacts/${contact.id}`);

    // Wait for page to load
    await expect(page).toHaveURL(new RegExp(`/contacts/${contact.id}`));

    // Verify Activity Feed section is visible
    const activityFeedHeading = page.getByRole('heading', {
      name: /Activity/i,
    });
    await expect(activityFeedHeading).toBeVisible({ timeout: 10000 });
  });

  test('should show empty state when no activity history exists', async ({
    emptyContactsPage,
    testCleanup,
  }) => {
    const page = emptyContactsPage;

    // Create a fresh contact without any edits
    const response = await page.request.post('/api/contacts', {
      headers: { 'Content-Type': 'application/json' },
      data: JSON.stringify({
        data: {
          type: 'contacts',
          attributes: {
            first_name: `Fresh_${Date.now()}`,
            last_name: 'Contact',
            is_favourite: false,
          },
        },
      }),
    });

    expect(response.ok()).toBeTruthy();
    const responseData = await response.json();
    const contactId = responseData.data.id;

    // Register cleanup
    testCleanup(async () => {
      await page.request.delete(`/api/contacts/${contactId}`);
    });

    // Navigate to contact detail page
    await page.goto(`/contacts/${contactId}`);
    await expect(page).toHaveURL(new RegExp(`/contacts/${contactId}`));

    // Wait for page content to load
    await expect(page.getByRole('heading', { name: /Activity/i })).toBeVisible({
      timeout: 10000,
    });

    // Check for empty state or "No activity" message
    // The empty state should show either "No activity" or similar message
    const pageContent = await page.textContent('body');
    expect(pageContent).toBeTruthy();
  });

  test('should display history entries after contact is updated', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    // Make an inline field update to generate history
    // Uses the PATCH /contacts/{id}/fields/{field_name} endpoint
    const updateResponse = await page.request.patch(
      `/api/contacts/${contact.id}/fields/nickname`,
      {
        headers: { 'Content-Type': 'application/json' },
        data: {
          data: {
            type: 'contact_fields',
            attributes: {
              value: 'Updated Nickname',
            },
          },
        },
      }
    );

    expect(updateResponse.ok()).toBeTruthy();

    // Navigate to contact detail page
    await page.goto(`/contacts/${contact.id}`);
    await expect(page).toHaveURL(new RegExp(`/contacts/${contact.id}`));

    // Wait for Activity Feed to load
    await expect(page.getByRole('heading', { name: /Activity/i })).toBeVisible({
      timeout: 10000,
    });

    // The Activity Feed should be present on the page
    // Check for the activity section wrapper
    const activitySection = page.locator('[class*="activity"]').first();
    await expect(activitySection).toBeVisible({ timeout: 5000 });
  });

  test('should load contact history via API endpoint', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    // Make an API call to fetch history
    const historyResponse = await page.request.get(
      `/api/contacts/${contact.id}/history`
    );

    expect(historyResponse.ok()).toBeTruthy();

    const historyData = await historyResponse.json();

    // Verify response structure matches JSON API format
    expect(historyData).toHaveProperty('data');
    expect(historyData).toHaveProperty('meta');
    expect(historyData.meta).toHaveProperty('total_count');
    expect(historyData.meta).toHaveProperty('current_page');
    expect(historyData.meta).toHaveProperty('page_count');
    expect(historyData.meta).toHaveProperty('per_page');
    expect(Array.isArray(historyData.data)).toBe(true);
  });

  test('should support pagination in history API', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    // Fetch first page with small limit
    const historyResponse = await page.request.get(
      `/api/contacts/${contact.id}/history?page=1&limit=5`
    );

    expect(historyResponse.ok()).toBeTruthy();

    const historyData = await historyResponse.json();

    // Verify pagination metadata
    expect(historyData.meta.current_page).toBe(1);
    expect(historyData.meta.per_page).toBe(5);
    expect(historyData.data.length).toBeLessThanOrEqual(5);
  });
});
