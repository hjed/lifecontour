import { Page } from '@playwright/test';
import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

/**
 * Generate an ISO datetime string offset from today by the given number of days.
 * Uses 12:00 (noon) UTC to ensure it lands on the same day in any timezone.
 */
function relativeDate(dayOffset: number, hour: number = 12): string {
  const d = new Date();
  d.setUTCHours(12, 0, 0, 0);
  d.setUTCDate(d.getUTCDate() + dayOffset);
  d.setUTCHours(hour, 0, 0, 0);
  return d.toISOString();
}

/**
 * Get YYYY-MM-DD for the ID of the summary in UTC
 */
function getFormattedDateId(dayOffset: number): string {
  const d = new Date();
  d.setUTCHours(12, 0, 0, 0);
  d.setUTCDate(d.getUTCDate() + dayOffset);
  const year = d.getUTCFullYear();
  const month = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/** Create two journals on the same day so the day qualifies for a summary. */
async function createTwoJournalsForDay(
  dataManager: TestDataManager,
  dayOffset: number,
  options?: { titles?: [string, string]; contents?: [string, string] }
): Promise<void> {
  const titles = options?.titles ?? ['Journal 1', 'Journal 2'];
  const contents = options?.contents ?? ['Content 1', 'Content 2'];

  await dataManager.createJournal({
    title: titles[0],
    content: contents[0],
    event_date_range: {
      start: relativeDate(dayOffset, 1),
      end: relativeDate(dayOffset, 2),
    },
  });
  await dataManager.createJournal({
    title: titles[1],
    content: contents[1],
    event_date_range: {
      start: relativeDate(dayOffset, 3),
      end: relativeDate(dayOffset, 4),
    },
  });
}

/** Build a JSON:API daily-summary response body. */
function buildSummaryResponse(
  dateId: string,
  overrides: Record<string, unknown> = {}
): string {
  return JSON.stringify({
    data: {
      type: 'journal-daily-summaries',
      id: dateId,
      attributes: {
        summary_date: dateId,
        summary_text: 'Mocked summary',
        journal_count: 2,
        event_count: 0,
        contact_count: 0,
        status: 'GENERATED',
        ...overrides,
      },
    },
  });
}

/** Mock the GET daily-summary endpoint for a given date. */
async function mockDailySummaryRoute(
  page: Page,
  dateId: string,
  overrides: Record<string, unknown> = {},
  delayMs = 0
): Promise<void> {
  await page.route(`**/api/journals/daily-summary/${dateId}`, async route => {
    if (delayMs > 0) {
      await new Promise(resolve => setTimeout(resolve, delayMs));
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: buildSummaryResponse(dateId, overrides),
    });
  });
}

test.describe('Journals AI Daily Summary', () => {
  test('should not show summary generation option for days with less than 2 journals', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dayOffset = -1; // Yesterday
    const journalDateId = getFormattedDateId(dayOffset);

    // Create only 1 journal for the day
    await dataManager.createJournal({
      title: 'Only one journal today',
      content: 'Not enough for a summary',
      event_date_range: {
        start: relativeDate(dayOffset, 1),
        end: relativeDate(dayOffset, 2),
      },
    });

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await authenticatedPage.goto('/journals');

    // The journal should be visible
    await expect(
      authenticatedPage.getByText('Only one journal today')
    ).toBeVisible({ timeout: 10000 });

    // The Generate AI Summary button should NOT be visible
    const generateBtn = authenticatedPage.getByTestId(
      `generate-summary-btn-${journalDateId}`
    );
    await expect(generateBtn).not.toBeVisible();
  });

  test('should generate and display read-only daily summary for populated days', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dayOffset = -2;
    const journalDateId = getFormattedDateId(dayOffset);

    await createTwoJournalsForDay(dataManager, dayOffset, {
      titles: ['Morning run', 'Evening reflections'],
      contents: ['Felt great', 'Good day overall'],
    });

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    // Mock the daily summary generation API to avoid hitting Gemini in E2E
    await mockDailySummaryRoute(
      authenticatedPage,
      journalDateId,
      {
        summary_text:
          'This is a mocked AI summary for the day. A very productive day.',
        mood_average: 8,
      },
      500
    );

    await authenticatedPage.goto('/journals');

    // Wait for the journals to load
    await expect(authenticatedPage.getByText('Morning run')).toBeVisible({
      timeout: 10000,
    });

    // The Generate AI Summary button SHOULD be visible
    const generateBtn = authenticatedPage.getByTestId(
      `generate-summary-btn-${journalDateId}`
    );
    await expect(generateBtn).toBeVisible();

    // Click it
    await generateBtn.click();

    // Should show loading state
    await expect(
      authenticatedPage.getByTestId(`summary-loading-${journalDateId}`)
    ).toBeVisible();

    // Eventually the summary should render
    const summaryCard = authenticatedPage.getByTestId(
      `summary-card-${journalDateId}`
    );
    await expect(summaryCard).toBeVisible({ timeout: 5000 });

    // Verify text and stats
    await expect(
      authenticatedPage.getByTestId(`summary-text-${journalDateId}`)
    ).toContainText('This is a mocked AI summary');
    await expect(summaryCard.getByText('2')).toBeVisible(); // journal count
    await expect(summaryCard.getByText('8.0/10')).toBeVisible(); // mood (.toFixed(1) renders 8 → 8.0)

    // Verify it is read-only (no inputs or textareas)
    const inputs = summaryCard.locator('input, textarea');
    await expect(inputs).toHaveCount(0);
  });

  test('should allow regenerating an existing summary', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dayOffset = -3;
    const journalDateId = getFormattedDateId(dayOffset);

    await createTwoJournalsForDay(dataManager, dayOffset);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    // Mock the initial fetch
    await mockDailySummaryRoute(authenticatedPage, journalDateId, {
      summary_text: 'Initial summary',
    });

    // Mock the regenerate POST
    let regenerateCalled = false;
    await authenticatedPage.route(
      `**/api/journals/daily-summary/${journalDateId}/regenerate`,
      async route => {
        if (route.request().method() === 'POST') {
          regenerateCalled = true;
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: buildSummaryResponse(journalDateId, {
              summary_text: 'Regenerated summary text',
              status: 'GENERATING',
            }),
          });
        } else {
          await route.continue();
        }
      }
    );

    await authenticatedPage.goto('/journals');

    const generateBtn = authenticatedPage.getByTestId(
      `generate-summary-btn-${journalDateId}`
    );
    await generateBtn.click();

    // Wait for initial summary
    await expect(
      authenticatedPage.getByTestId(`summary-text-${journalDateId}`)
    ).toContainText('Initial summary');

    // Click refresh
    const refreshBtn = authenticatedPage.getByTestId(
      `refresh-summary-btn-${journalDateId}`
    );
    await refreshBtn.click();

    // Verify it called the POST route and updated the UI (should show regenerating badge or text)
    expect(regenerateCalled).toBe(true);
    await expect(authenticatedPage.getByText('Generating...')).toBeVisible();
  });
});
