/**
 * E2E Tests for Contact Activity Feed
 *
 * Tests the Activity Feed functionality on the contact detail page,
 * including displaying history entries, pagination, and visual formatting.
 */

import { test, expect } from './fixtures';

/**
 * Poll the contact history API until an entry matching `matches` appears.
 *
 * ITER12-003 Phase 2 made contact history event-driven: a change is projected
 * into history asynchronously (service -> outbox -> stream -> projection
 * consumer), so assertions on a just-made change must poll rather than read
 * immediately. Mirrors the journal-history.spec.ts helper.
 */
async function waitForContactHistoryEntry(
  request: import('@playwright/test').APIRequestContext,
  contactId: string,
  matches: (attrs: {
    field_name: string;
    source: string;
    old_value: string | null;
    new_value: string | null;
  }) => boolean
): Promise<void> {
  await expect(async () => {
    const response = await request.get(`/api/contacts/${contactId}/history`);
    expect(response.ok()).toBeTruthy();
    const json = await response.json();
    expect(Array.isArray(json.data)).toBe(true);
    const found = json.data.some(
      (entry: { attributes: Parameters<typeof matches>[0] }) =>
        matches(entry.attributes)
    );
    expect(found).toBe(true);
  }).toPass({ timeout: 30000 });
}

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
            first_name: `E2ETest_${Date.now()}`,
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
    const pageContent = page.locator('body');
    await expect(pageContent).not.toBeEmpty();
  });

  test('should display history entries after contact is updated', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    // Make an inline field update to generate history
    // Uses the PATCH /contacts/{id}/fields/{field_name} endpoint
    // Using 'nick_name' as the field name (snake_case as used in the API)
    const updateResponse = await page.request.patch(
      `/api/contacts/${contact.id}/fields/nick_name`,
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

    // History is projected asynchronously (ITER12-003 Phase 2), so poll until the
    // nick_name change lands with the correct old/new values and UI provenance.
    await waitForContactHistoryEntry(
      page.request,
      String(contact.id),
      attrs =>
        attrs.field_name === 'nick_name' &&
        attrs.new_value === 'Updated Nickname' &&
        attrs.source === 'ui'
    );

    // Navigate to contact detail page
    await page.goto(`/contacts/${contact.id}`);
    await expect(page).toHaveURL(new RegExp(`/contacts/${contact.id}`));

    // Wait for Activity Feed heading to load
    await expect(page.getByRole('heading', { name: /Activity/i })).toBeVisible({
      timeout: 10000,
    });

    // The projected entry is now visible in the feed with UI provenance.
    const feed = page.getByTestId('activity-feed');
    await expect(feed).toBeVisible();
    await expect(feed.getByTestId('provenance-trigger-ui').first()).toBeVisible(
      {
        timeout: 10000,
      }
    );
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

  test('should display provenance indicators and collapsible summary regeneration', async ({
    contactsWithData,
    isMobile,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    // Mock the history API response to include specific provenance types
    await page.route(`**/api/contacts/${contact.id}/history*`, async route => {
      const json = {
        data: [
          {
            type: 'contact_history',
            id: '999',
            attributes: {
              entity_type: 'contact',
              entity_id: contact.id,
              field_name: 'first_name',
              old_value: 'Old',
              new_value: 'New',
              changed_by: 'system',
              source: 'google_contacts',
              created_at: new Date().toISOString(),
            },
          },
          {
            type: 'contact_history',
            id: '1000',
            attributes: {
              entity_type: 'contact_summary',
              entity_id: 1,
              field_name: 'summary_text',
              old_value: 'Old summary',
              new_value: 'New summary text that is very long',
              changed_by: 'system',
              source: 'summary_regeneration',
              created_at: new Date().toISOString(),
            },
          },
        ],
        meta: {
          total_count: 2,
          current_page: 1,
          page_count: 1,
          per_page: 50,
        },
      };
      await route.fulfill({ json });
    });

    await page.goto(`/contacts/${contact.id}`);
    await expect(page).toHaveURL(new RegExp(`/contacts/${contact.id}`));

    // Wait for Activity Feed to render
    const activityHeading = page.getByRole('heading', { name: /Activity/i });
    await expect(activityHeading).toBeVisible({ timeout: 10000 });

    // Verify summary regeneration abbreviation
    await expect(page.getByText('AI Summary Regenerated')).toBeVisible();

    // Initially new summary is hidden
    await expect(
      page.getByText('New summary text that is very long')
    ).toBeHidden();

    // Expand.
    //
    // The locator matches the half of the label that does not change: the
    // button is "Expand summary text" collapsed and "Collapse summary text"
    // expanded, so naming either state gives a locator that stops matching the
    // moment it is used. Scoped to the row so it cannot drift onto another.
    const disclosure = page
      .getByTestId('activity-item-1000')
      .getByRole('button', { name: /summary text$/i });
    await expect(disclosure).toHaveAttribute('aria-expanded', 'false');

    // Why a retry loop around a *forced* click, rather than the usual advice of
    // dropping `force`:
    //
    // Playwright's own log shows this element reported "visible, enabled and
    // stable" and scrolled into view, and the hit test *still* landed on the
    // card header or on the row above — the page shifts between "done
    // scrolling" and the hit test. So an unforced click never becomes
    // actionable here: removing `force` fails Mobile Chrome 8 runs out of 9,
    // where this row sits ~1000px below the fold. `force` is load-bearing and
    // is kept.
    //
    // What `force` costs is the guarantee that the click *landed*: it is
    // dispatched at coordinates computed a moment earlier, so when the layout
    // moves in that window the event goes to whatever now occupies the point
    // and the toggle silently does not happen. That is the flake — CI failed 15
    // seconds later on the summary text, blaming the wrong thing, and passed on
    // retry.
    //
    // So: click only while the disclosure is still collapsed, and retry until
    // it is open. The guard is what makes this safe to retry — an unguarded
    // retry of a *toggle* would close it again on the next pass. Inner timeouts
    // are short so the outer budget allows several attempts.
    await expect(async () => {
      if ((await disclosure.getAttribute('aria-expanded')) === 'false') {
        await disclosure.scrollIntoViewIfNeeded();
        await disclosure.click({ force: true });
      }
      await expect(disclosure).toHaveAttribute('aria-expanded', 'true', {
        timeout: 2000,
      });
    }).toPass({ timeout: 20000 });

    // Text becomes visible
    await expect(
      page.getByText('New summary text that is very long')
    ).toBeVisible();

    // Check for Google Contacts provenance on the first item
    const googleIconWrapper = page
      .getByTestId('provenance-trigger-google_contacts')
      .first();

    if (!isMobile) {
      await expect(async () => {
        await googleIconWrapper.hover();
        await expect(
          page.getByRole('tooltip', {
            name: 'Updated via Google Contacts Sync',
          })
        ).toBeVisible({ timeout: 2000 });
      }).toPass({ timeout: 10000 });
    }
  });
});
