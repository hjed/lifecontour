import { test, expect } from './fixtures';

import { JournalType } from '../../src/types/journals';

// Using authenticated context to access journal details directly
test.describe('Journal Type Management', () => {
  test('can add and remove journal types via UI', async ({
    authenticatedPage: page,
    testCleanup,
    isMobile,
  }) => {
    if (isMobile) test.skip();
    // Create a test journal via API directly to test type management UI
    const response = await page.request.post('/api/journals', {
      data: {
        data: {
          type: 'journal',
          attributes: {
            title: 'Test Journal for Type Management',
            content: 'This journal will be used to test adding/removing types.',
            journal_types: [JournalType.NOTE],
            event_date_range: {
              start: new Date().toISOString(),
              end: new Date().toISOString(),
            },
          },
        },
      },
    });

    if (!response.ok()) {
      const errorData = await response.json();
      console.error(JSON.stringify(errorData, null, 2));
    }
    expect(response.ok()).toBeTruthy();
    const data = await response.json();
    const testJournalId = data.data.id;

    // Register cleanup
    testCleanup(async () => {
      if (testJournalId) {
        await page.request.delete(`/api/journals/${testJournalId}`);
      }
    });

    // Go to the journal detail page
    await page.goto(`/journals/${testJournalId}`);

    // Check initial state - NOTE type should be present
    const typeManager = page.getByTestId('journal-type-manager');
    await expect(typeManager).toBeVisible();
    await expect(
      page.getByTestId(`manage-type-${JournalType.NOTE}`)
    ).toBeVisible();

    // Add a new type (PLAN)
    await page.getByTestId('add-type-button').click();

    // Wait for the API response after clicking the option
    await Promise.all([
      page.waitForResponse(
        response =>
          response.url().includes(`/api/journals/${testJournalId}/types`) &&
          response.request().method() === 'POST' &&
          response.ok()
      ),
      page.getByTestId(`add-type-option-${JournalType.PLAN}`).click(),
    ]);

    // Verify PLAN type was added (badge appears)
    await expect(
      page.getByTestId(`manage-type-${JournalType.PLAN}`)
    ).toBeVisible();

    // We mock window.confirm since it blocks Playwright
    // Register dialog handler BEFORE the action that triggers it
    page.on('dialog', dialog => dialog.accept());

    // Hover over PLAN to reveal remove button and remove it
    // Wait for tooltip/hovercard
    await page.getByTestId(`manage-type-${JournalType.PLAN}`).hover();

    // Wait for the HoverCard to fully appear before clicking
    await expect(
      page.getByTestId(`remove-type-${JournalType.PLAN}`)
    ).toBeVisible();

    // Click remove inside the hovercard
    await Promise.all([
      page.waitForResponse(
        response =>
          response
            .url()
            .includes(
              `/api/journals/${testJournalId}/types/${JournalType.PLAN}`
            ) &&
          response.request().method() === 'DELETE' &&
          response.ok()
      ),
      page.getByTestId(`remove-type-${JournalType.PLAN}`).click(),
    ]);

    // Verify it was removed successfully
    await expect(
      page.getByTestId(`manage-type-${JournalType.PLAN}`)
    ).not.toBeVisible();
  });
});
