import { test, expect } from './fixtures';

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

    // Calculate dates
    const today = new Date();

    const pastDate = new Date(today);
    pastDate.setDate(today.getDate() - 7);

    const futureDate = new Date(today);
    futureDate.setDate(today.getDate() + 7);

    // Create 3 journals spaced apart > chunk size (7 days)
    await dataManager.createJournals([
      {
        title: 'Present Journal',
        content: 'This happened today',
        event_date_range: {
          start: today.toISOString(),
          end: today.toISOString(),
        },
      },
      {
        title: 'Past Journal',
        content: 'This happened 7 days ago',
        event_date_range: {
          start: pastDate.toISOString(),
          end: pastDate.toISOString(),
        },
      },
      {
        title: 'Future Journal',
        content: 'This will happen 7 days in future',
        event_date_range: {
          start: futureDate.toISOString(),
          end: futureDate.toISOString(),
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

    // 2. Initial state: Present should be visible
    await expect(
      page.getByRole('heading', { name: /Present Journal/i })
    ).toBeVisible();
    // 3. Scroll Down (to FUTURE) -> Should trigger fetchNextPage
    const bottomSentinel = page.getByTestId('journal-bottom-sentinel');

    // Use toPass to retry scroll + assertion together, since a single
    // scrollIntoViewIfNeeded may not reliably trigger the IntersectionObserver
    // in CI headless environments.
    await expect(async () => {
      await bottomSentinel.scrollIntoViewIfNeeded();
      await expect(
        page.getByRole('heading', { name: /Future Journal/i })
      ).toBeVisible({ timeout: 5000 });
    }).toPass({ timeout: 30000 });

    // 4. Scroll Up (to PAST) -> Should trigger fetchPreviousPage
    const topSentinel = page.getByTestId('journal-top-sentinel');

    // Use toPass to retry scroll + assertion together for reliability.
    // scrollIntoViewIfNeeded on the top sentinel reliably brings it into the
    // viewport and triggers the IntersectionObserver, unlike window.scrollTo(0,0)
    // which may not fire the observer in headless CI.
    await expect(async () => {
      await topSentinel.scrollIntoViewIfNeeded();
      await expect(
        page.getByRole('heading', { name: /Past Journal/i })
      ).toBeVisible({ timeout: 5000 });
    }).toPass({ timeout: 30000 });
  });
});
