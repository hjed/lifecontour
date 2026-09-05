import { test, expect } from './fixtures';
import { reachForMoreJournals } from './utils/journal-list-scroll';

function relativeDate(dayOffset: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + dayOffset);
  d.setUTCHours(12, 0, 0, 0);
  return d.toISOString();
}

test.describe('Journal Infinite Scroll', () => {
  test('should load past and future journals seamlessly', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );

    // Clear existing data
    await dataManager.clearAllJournals();

    // Filler journals inside the initial chunk window (anchor ±3 days) make
    // the first page taller than any project's viewport plus the sentinels'
    // 200px observation margin. Without them the top sentinel starts in view
    // on tall viewports (Mobile Chrome) and the list correctly fills the
    // viewport by loading the past chunk immediately — which would make the
    // "hidden before scrolling" assertion below viewport-dependent.
    const fillerJournals = [-3, -2, -1].flatMap(dayOffset =>
      [1, 2].map(n => ({
        title: `Filler Journal ${dayOffset}/${n}`,
        content: 'Padding content so the initial chunk overflows the viewport',
        event_date_range: {
          start: relativeDate(dayOffset),
          end: relativeDate(dayOffset),
        },
      }))
    );

    // Create 3 journals spaced apart > chunk size (7 days)
    await dataManager.createJournals([
      ...fillerJournals,
      {
        title: 'Present Journal',
        content: 'This happened today',
        event_date_range: {
          start: relativeDate(0),
          end: relativeDate(0),
        },
      },
      {
        title: 'Past Journal',
        content: 'This happened 7 days ago',
        event_date_range: {
          start: relativeDate(-7),
          end: relativeDate(-7),
        },
      },
      {
        title: 'Future Journal',
        content: 'This will happen 7 days in future',
        event_date_range: {
          start: relativeDate(7),
          end: relativeDate(7),
        },
      },
    ]);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    // 1. Visit page
    await page.goto('/journals');
    await expect(page.getByTestId('journals-list-ready')).toBeVisible();
    // Use element-based assertion instead of networkidle

    // 2. Initial state: Present should be visible, others shouldn't
    await expect(
      page.getByRole('heading', { name: /Present Journal/i })
    ).toBeVisible();
    await expect(
      page.getByRole('heading', { name: /Past Journal/i })
    ).toBeHidden();

    // 3. Scroll Down (to FUTURE) -> Should trigger fetchNextPage
    // The reach is a wheel gesture rather than a conditional scroll, so it
    // registers even when the sentinel is already on screen — see
    // reachForMoreJournals. toPass retries the reach with the assertion, in
    // case the fetch it asked for was skipped while another was in flight.
    await expect(async () => {
      await reachForMoreJournals(page, 'future');
      await expect(
        page.getByRole('heading', { name: /Future Journal/i })
      ).toBeVisible({ timeout: 3000 });
    }).toPass({ timeout: 30000 });

    // 4. Scroll Up (to PAST) -> Should trigger fetchPreviousPage
    await expect(async () => {
      await reachForMoreJournals(page, 'past');
      await expect(
        page.getByRole('heading', { name: /Past Journal/i })
      ).toBeVisible({ timeout: 3000 });
    }).toPass({ timeout: 30000 });
  });
});
